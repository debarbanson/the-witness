"""Model settings: provider, base URL, model id and key name in one place.

Research, vision and the search fallback run on the Meta Model API
(Responses calls). Passage-only support checks can run on Meta (VERIFY)
or on the open-weights Muse Spark Open via Baseten (VERIFY_OPEN, Chat
Completions; credits granted 27 Oct). Token use is tallied per provider
for the cost report, and a hard daily cap guards public spending.
"""

import contextlib
import contextvars
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix platforms
    fcntl = None


class ModelError(Exception):
    """A model is misconfigured (its key is missing)."""


class SpendingCapExceeded(ModelError):
    """The daily spending cap was reached; no further paid call today."""


class AccountingError(ModelError):
    """Spending accounting is unavailable or corrupt; fail closed."""


class JobCancelled(BaseException):
    """The visitor cancelled the job (a closed tab cancels it).

    BaseException on purpose, like asyncio cancellation: per-claim and
    per-paint guards must not convert it into dropped work. Only the
    job entry point catches it, into an honest cancelled result."""


class JobDeadlineExceeded(BaseException):
    """The job ran past its deadline; same handling as cancelled."""


# Prices verified 29 Oct 2026 against
# https://dev.meta.ai/docs/pricing-rate-limits (Meta) and the Baseten
# grant terms ($1.25 per M tokens in and out).
PRICE_PER_M = {
    ("meta", "muse-spark-1.3"): (1.25, 4.25),
    ("baseten", "meta-models/muse-spark-open-1026"): (1.25, 1.25),
}
PER_CALL_USD = {
    ("meta", "muse-image-1.0"): 0.01,  # per generated image; failures unbilled
    ("meta", "sam-3.1"): 0.0025,  # per segmented image
}
WEB_SEARCH_USD = 0.0025  # per search, counted from web_search_call items


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    base_url: str
    model: str
    key_name: str
    effort: str | None = None  # reasoning effort; None keeps the default
    temperature: float | None = None  # None keeps the default; 0 steadies checks
    workers: int = 6  # parallel calls; Baseten allows more (2M tokens/min)
    timeout: float = 120  # per-call seconds; research and painting run longer
    ceiling_usd: float = 0.25  # conservative max reserved before each call
    max_output_tokens: int | None = None  # bound injected into the call


RESEARCH = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    timeout=300,  # web research with reasoning runs for minutes
    ceiling_usd=2.00,
    max_output_tokens=16384,
)

VISION = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
    ceiling_usd=0.25,
    max_output_tokens=2048,
)

VERIFY = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
    temperature=0,  # probed 27 Oct: accepted; seed is not in the SDK surface
    ceiling_usd=0.10,
    max_output_tokens=2048,
)

# Step 5 shares the verify setting until it needs its own.
CHECK = VERIFY

# Step 4: anchored era painting. Settings travel inside the image
# tool, never as top-level parameters; there is no seed.
PAINT = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-image-1.0",
    key_name="MODEL_API_KEY",
    timeout=600,  # chained image turns take minutes; observed over 200 s
    ceiling_usd=0.10,
)

# Steps 1 and 6: segmentation, same key as everything Meta.
SAM = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="sam-3.1",
    key_name="MODEL_API_KEY",
    ceiling_usd=0.01,
)

# Open-weights support checks on Baseten (credits granted 27 Oct). The
# hackathon key only works with the -1026 model name, not the name in
# Baseten's own docs. Chat Completions path; Meta stays on Responses.
VERIFY_OPEN = ModelSpec(
    provider="baseten",
    base_url="https://inference.baseten.co/v1",
    model="meta-models/muse-spark-open-1026",
    key_name="BASETEN_API_KEY",
    temperature=0,
    # 2M tokens/min throughput: support calls are small (a claim plus
    # a few passages), so 10 workers with the first two vote rounds in
    # parallel stay inside.
    workers=10,
    timeout=180,  # the open model always reasons, so votes run longer
    ceiling_usd=0.10,
    max_output_tokens=2048,
)


SEARCH_BUDGET_PER_JOB = 200  # web searches; the job stops paying past this


_CLIENTS = {}

FAKE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGM8ISfHgA0w"
    "YRUdtBIA0MoBFD5jqJkAAAAASUVORK5CYII=")


class _FakeSDKResponse(dict):
    """A scripted provider answer shaped like an SDK response."""

    @property
    def usage(self):
        return self.get("usage", {})

    def model_dump_json(self):
        return json.dumps({k: v for k, v in self.items()})


def _fake_texts(value) -> str:
    """All input text in a Responses call, for answer routing."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_fake_texts(v) for v in value)
    if isinstance(value, dict):
        if value.get("type") == "input_text":
            return str(value.get("text", ""))
        return "\n".join(_fake_texts(v) for v in value.values())
    return ""


def _fake_message(text, annotations=()) -> dict:
    return {"type": "message", "content": [
        {"type": "output_text", "text": text,
         "annotations": list(annotations)}]}


_FAKE_URL = "https://en.wikipedia.org/wiki/Fake_Mill"


def _fake_research_payload() -> dict:
    events = [
        {"year": 1850, "event": "built",
         "detail": "The mill was built in 1850.", "visible_change": "",
         "date_text": "1850"},
        {"year": 1900, "event": "burnt",
         "detail": "The mill burnt down in 1900.",
         "visible_change": "roof lost", "date_text": "1900"},
    ]
    sources = [_FAKE_URL]
    return {
        "output": [
            {"type": "web_search_call", "results": [
                {"url": _FAKE_URL,
                 "snippet": "The mill was built in 1850 and burnt in 1900."}]},
            _fake_message(
                json.dumps({"events": events, "sources": sources}),
                [{"type": "url_citation", "url": _FAKE_URL,
                  "title": "Fake Mill"}]),
        ],
        "usage": {"prompt_tokens": 500, "completion_tokens": 200,
                  "total_tokens": 700},
    }


def _fake_vote_payload() -> dict:
    quote = "The mill was built in 1850."
    return {
        "output": [_fake_message(json.dumps({
            "verdict": "supported", "quote": quote, "url": _FAKE_URL,
            "support": [{"url": _FAKE_URL, "supports": True,
                         "quote": quote}]}))],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "total_tokens": 150},
    }


class _FakeResponses:
    def __init__(self, spec):
        self._spec = spec

    def create(self, model=None, **kwargs):
        import re as _re
        import time as _time

        _time.sleep(float(os.environ.get("WITNESS_FAKE_DELAY_S", "0")))
        if model == "muse-image-1.0":
            return _FakeSDKResponse({
                "id": f"fake-{uuid.uuid4().hex[:8]}",
                "output": [{"type": "image_generation_call",
                            "result": FAKE_PNG_B64}],
                "usage": {}})
        if model == "sam-3.1":
            return _FakeSDKResponse({"output": [_fake_message("no mask")]})
        text = _fake_texts(kwargs.get("input", ""))
        if "Which one does the photo show" in text:
            first = _re.findall(r"^(\d+)\.\s+([^(\n]+)", text, _re.M)
            pick = f"{first[0][0]} {first[0][1].strip()}" if first else "NONE"
            return _FakeSDKResponse({
                "output": [_fake_message(f"{pick}\nConfident.")],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                          "total_tokens": 110}})
        if "Second look" in text:
            return _FakeSDKResponse({
                "output": [_fake_message("YES\nIt shows the object.")]})
        if "Did this change actually happen" in text:
            return _FakeSDKResponse({
                "output": [_fake_message('{"completed": true}')]})
        if "Claim to check:" in text:
            return _FakeSDKResponse(_fake_vote_payload())
        if "MATCHES only if" in text:
            return _FakeSDKResponse({
                "output": [_fake_message("MATCHES whole.")]})
        if "What happened to the" in text:
            return _FakeSDKResponse(_fake_research_payload())
        return _FakeSDKResponse({
            "output": [_fake_message("I stood here through the years.")]})


class _FakeChatCompletions:
    def create(self, model=None, messages=(), **kwargs):
        import time as _time

        _time.sleep(float(os.environ.get("WITNESS_FAKE_DELAY_S", "0")))
        return {"choices": [{"message": {
            "content": json.dumps({
                "verdict": "supported",
                "quote": "The mill was built in 1850.", "url": _FAKE_URL,
                "support": []}),
            "reasoning_content": "fake reasoning"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                          "total_tokens": 150}}


class _FakeChat:
    completions = _FakeChatCompletions()


class _FakeProviderClient:
    """Scripted staging provider: deterministic answers, real metering.

    Gated by WITNESS_FAKE_PROVIDER for the staging abuse tests. Spend,
    reservations, quotas, cancellation and deadlines all run for real;
    only the model answers are canned."""

    def __init__(self, spec):
        self.responses = _FakeResponses(spec)
        self.chat = _FakeChat()


def client_for(spec, environ=None):
    """One OpenAI-compatible client per spec and key, shared by every
    call. Key never leaves the environment."""
    from openai import OpenAI

    env = environ if environ is not None else os.environ
    if env.get("WITNESS_FAKE_PROVIDER"):
        return _FakeProviderClient(spec)
    key = env.get(spec.key_name)
    if not key:
        raise ModelError(f"{spec.key_name} is not set (needed for {spec.provider}/{spec.model})")
    cache_key = (spec.base_url, spec.key_name, key, spec.timeout)
    client = _CLIENTS.get(cache_key)
    if client is None:
        client = OpenAI(base_url=spec.base_url, api_key=key,
                        timeout=spec.timeout, max_retries=1)
        _CLIENTS[cache_key] = client
    return client


def _count_searches(response) -> int:
    """Web searches behind a Responses call, from its tool items."""
    if isinstance(response, dict):
        output = response.get("output", [])
        kinds = [item.get("type") for item in output if isinstance(item, dict)]
    else:
        kinds = [getattr(item, "type", None)
                 for item in getattr(response, "output", []) or []]
    return sum(1 for kind in kinds if kind == "web_search_call")


def _bound_output(key, spec, kwargs) -> None:
    """Cap output tokens at the spec bound; an explicit smaller ask wins."""
    if spec.max_output_tokens is None:
        return
    asked = kwargs.get(key)
    if asked is None:
        kwargs[key] = spec.max_output_tokens
    else:
        kwargs[key] = min(asked, spec.max_output_tokens)


def _admit_call() -> None:
    """Fail a paid call whose job already spent its search budget."""
    if current_ledger().searches >= SEARCH_BUDGET_PER_JOB:
        raise SpendingCapExceeded(
            f"job web-search budget spent ({SEARCH_BUDGET_PER_JOB}); stopping")


class JobControl:
    """One job's cancel token plus deadline, shared by every thread."""

    def __init__(self, deadline_s=None):
        import threading
        import time as _time

        self._time = _time
        self._cancelled = threading.Event()
        self.deadline = (None if deadline_s is None
                         else _time.monotonic() + deadline_s)

    def cancel(self) -> None:
        """Cancel the job; in-flight calls finish, nothing new starts."""
        self._cancelled.set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled("job cancelled")
        if self.deadline is not None and self._time.monotonic() > self.deadline:
            raise JobDeadlineExceeded("job deadline passed")


_CONTROL: contextvars.ContextVar = contextvars.ContextVar(
    "witness_job_control", default=None)


def _check_control() -> None:
    """Raise when the job was cancelled or ran past its deadline."""
    control = _CONTROL.get()
    if control is not None:
        control.check()


@contextlib.contextmanager
def job_control(deadline_s=None, control=None):
    """Run under a job control (an explicit control wins over a fresh
    deadline). Worker threads inherit it through submit_context."""
    owned = control if control is not None else JobControl(deadline_s)
    token = _CONTROL.set(owned)
    try:
        yield owned
    finally:
        _CONTROL.reset(token)


def with_job_control(fn):
    """Run a job entry point under its control: the `control` kwarg
    when given, else a fresh `deadline_s` (default 30 minutes)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with job_control(kwargs.get("deadline_s", 1800),
                         kwargs.get("control")):
            return fn(*args, **kwargs)

    return wrapper


def catch_job_halt(fn):
    """Turn a halted job into an honest result dict instead of a crash."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except JobCancelled as exc:
            return {"confirmed": False, "identified": False, "cached": False,
                    "cancelled": True, "error": str(exc)}
        except JobDeadlineExceeded as exc:
            return {"confirmed": False, "identified": False, "cached": False,
                    "deadline": True, "error": str(exc)}

    return wrapper


def _paid_call(spec, response, ticket=None):
    """Record one finished paid call on the job ledger and reconcile
    the reservation with the authority. Failures never reach here."""
    usage = getattr(response, "usage", None) if not isinstance(response, dict) else response.get("usage")
    searches = 0 if spec.provider == "baseten" else _count_searches(response)
    cost = current_ledger().note(spec.provider, spec.model, usage, searches=searches)
    if ticket is not None:
        _DAILY.reconcile(ticket, cost)
    return response


def respond(client, spec, **kwargs):
    """One Responses call: model id, reasoning effort, temperature and
    the output bound injected. The ceiling is reserved first; a failed
    call releases its reservation and records nothing."""
    if spec.effort is not None:
        kwargs["reasoning"] = {"effort": spec.effort}
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    _bound_output("max_output_tokens", spec, kwargs)
    _check_control()
    _admit_call()
    ticket = _DAILY.reserve(spec.ceiling_usd) if _DAILY is not None else None
    try:
        response = client.responses.create(model=spec.model, **kwargs)
    except Exception:
        if ticket is not None:
            _DAILY.reconcile(ticket, 0.0)
        raise
    return _paid_call(spec, response, ticket)


def chat(client, spec, messages, **kwargs):
    """One Chat Completions call (the Baseten path): model id,
    temperature and the output bound injected. No reasoning control:
    Muse Spark Open always reasons; read the answer with chat_answer.
    The ceiling is reserved first; a failed call releases its
    reservation and records nothing."""
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    _bound_output("max_tokens", spec, kwargs)
    _check_control()
    _admit_call()
    ticket = _DAILY.reserve(spec.ceiling_usd) if _DAILY is not None else None
    try:
        response = client.chat.completions.create(
            model=spec.model, messages=messages, **kwargs)
    except Exception:
        if ticket is not None:
            _DAILY.reconcile(ticket, 0.0)
        raise
    return _paid_call(spec, response, ticket)


def chat_answer(response) -> dict:
    """Final answer text, reasoning kept separate, token counts."""
    if isinstance(response, dict):
        message = response["choices"][0]["message"]
        content = message.get("content", "")
        reasoning = message.get("reasoning_content", "")
        usage = response.get("usage", {}) or {}
    else:
        message = response.choices[0].message
        content = message.content or ""
        reasoning = getattr(message, "reasoning_content", "") or ""
        usage = _usage_dict(getattr(response, "usage", None))
    return {"content": content, "reasoning": reasoning, "usage": usage}


class SpendingLedger:
    """Token and per-call spend. Totals keep the per-provider shape
    {provider: {prompt_tokens, completion_tokens, total_tokens}}."""

    def __init__(self):
        self.totals: dict = {}
        self.cost_usd = 0.0
        self.calls = 0
        self.searches = 0

    def note(self, provider, model, usage, searches=0) -> float:
        """Record one call; returns its cost in dollars."""
        self.searches += searches
        counts = _usage_dict(usage)
        if counts:
            totals = self.totals.setdefault(
                provider, {"prompt_tokens": 0, "completion_tokens": 0,
                           "total_tokens": 0})
            for key in totals:
                totals[key] += counts.get(key, 0)
        in_price, out_price = PRICE_PER_M.get((provider, model), (0.0, 0.0))
        cost = (counts.get("prompt_tokens", 0) / 1e6 * in_price
                + counts.get("completion_tokens", 0) / 1e6 * out_price
                + PER_CALL_USD.get((provider, model), 0.0)
                + searches * WEB_SEARCH_USD)
        self.cost_usd += cost
        self.calls += 1
        return cost


_JOB_LEDGER: contextvars.ContextVar = contextvars.ContextVar(
    "witness_job_ledger", default=None)
_GLOBAL_LEDGER = SpendingLedger()  # unattributed calls outside any job


def current_ledger() -> SpendingLedger:
    """This job's ledger, or the global one outside a job."""
    return _JOB_LEDGER.get() or _GLOBAL_LEDGER


@contextlib.contextmanager
def job_ledger():
    """One ledger for one job, from identify through export. Nested
    uses share the outer ledger, so a wrapped entry point never splits
    the job's spend. Worker threads inherit it only through
    submit_context."""
    existing = _JOB_LEDGER.get()
    if existing is not None:
        yield existing
        return
    token = _JOB_LEDGER.set(SpendingLedger())
    try:
        yield _JOB_LEDGER.get()
    finally:
        _JOB_LEDGER.reset(token)


def with_job_ledger(fn):
    """Run a job entry point under its job ledger (fresh at the top)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with job_ledger():
            return fn(*args, **kwargs)

    return wrapper


def submit_context(pool, fn, *args, **kwargs):
    """ThreadPool submit that carries the current job ledger along."""
    ctx = contextvars.copy_context()
    return pool.submit(lambda: ctx.run(fn, *args, **kwargs))


def reset_usage() -> None:
    """Clear job and unattributed totals (tests and fresh processes)."""
    global _GLOBAL_LEDGER
    _JOB_LEDGER.set(None)
    _GLOBAL_LEDGER = SpendingLedger()


def note_usage(provider: str, usage, model=None) -> None:
    """Add one call's token counts to this job's running totals."""
    current_ledger().note(provider, model, usage)


def usage_totals() -> dict:
    ledger = current_ledger()
    return {provider: dict(totals) for provider, totals in ledger.totals.items()}


def current_cost_usd() -> float:
    """This job's spend so far in dollars."""
    return current_ledger().cost_usd


class BudgetTicket:
    """One held reservation: the ceiling committed before a call."""

    def __init__(self, ceiling_usd: float):
        self.ceiling_usd = ceiling_usd


class BudgetAuthority:
    """One shared budget authority: every billable call reserves its
    conservative ceiling first and reconciles the actual cost after,
    so parallel calls can never spend the same unit twice.

    This file-backed authority is atomic on one machine (a thread lock
    plus a flock-guarded JSON file per day). Across Modal containers
    the same protocol runs behind a single max-concurrency-1 function,
    since a Dict alone is not atomic for read-modify-write. Corrupt or
    unreadable accounting fails closed: no reservation, no call."""

    def __init__(self, path, daily_cap_usd=None, daily_films=None,
                 visitor_films=None):
        import threading

        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cap_usd = daily_cap_usd
        self.daily_films = daily_films
        self.visitor_films = visitor_films
        self._mutex = threading.Lock()

    def _file(self):
        return self.dir / f"spending-{date.today().isoformat()}.json"

    @contextlib.contextmanager
    def _account(self):
        """The day's locked account for one atomic read-modify-write."""
        with self._mutex:
            try:
                handle = open(self._file(), "a+")
            except OSError as exc:
                raise AccountingError(
                    f"spending accounting unavailable: {exc}")
            try:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_EX)
                handle.seek(0)
                try:
                    raw = handle.read()
                    data = json.loads(raw) if raw.strip() else {}
                except (json.JSONDecodeError, ValueError):
                    raise AccountingError(
                        "spending accounting is corrupt; refusing to spend")
                if not isinstance(data, dict):
                    raise AccountingError(
                        "spending accounting is corrupt; refusing to spend")
                data.setdefault("date", date.today().isoformat())
                data.setdefault("total_usd", 0.0)
                data.setdefault("reserved_usd", 0.0)
                data.setdefault("calls", 0)
                data.setdefault("films", 0)
                data.setdefault("visitors", {})
                yield data
                handle.seek(0)
                handle.truncate()
                json.dump(data, handle)
            finally:
                handle.close()

    def _read(self) -> dict:
        if not self._file().exists():
            return {"total_usd": 0.0, "reserved_usd": 0.0, "calls": 0,
                    "films": 0, "visitors": {}}
        with self._mutex:
            try:
                raw = self._file().read_text()
            except OSError as exc:
                raise AccountingError(
                    f"spending accounting unavailable: {exc}")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, ValueError):
            raise AccountingError(
                "spending accounting is corrupt; refusing to spend")
        if not isinstance(data, dict):
            raise AccountingError(
                "spending accounting is corrupt; refusing to spend")
        return data

    def total_usd(self) -> float:
        return float(self._read().get("total_usd", 0.0))

    def reserved_usd(self) -> float:
        return float(self._read().get("reserved_usd", 0.0))

    def reserve(self, ceiling_usd: float) -> BudgetTicket:
        """Hold ceiling_usd of today's budget, or raise."""
        with self._account() as data:
            spent = float(data.get("total_usd", 0.0))
            held = float(data.get("reserved_usd", 0.0))
            if (self.cap_usd is not None
                    and spent + held + ceiling_usd > self.cap_usd):
                raise SpendingCapExceeded(
                    f"daily spending cap reached (${self.cap_usd:.2f}); "
                    f"try again tomorrow")
            data["reserved_usd"] = held + ceiling_usd
            return BudgetTicket(ceiling_usd)

    def reconcile(self, ticket: BudgetTicket, actual_usd: float) -> None:
        """Release a reservation and record what the call cost (0.0
        when it failed before billing)."""
        with self._account() as data:
            held = float(data.get("reserved_usd", 0.0))
            data["reserved_usd"] = max(0.0, held - ticket.ceiling_usd)
            data["total_usd"] = float(data.get("total_usd", 0.0)) + actual_usd
            data["calls"] = int(data.get("calls", 0)) + 1

    def admit(self, visitor: str) -> None:
        """Admit one film for a visitor under the daily and per-visitor
        quotas. A None quota means unlimited (the CLI default)."""
        with self._account() as data:
            films = int(data.get("films", 0))
            if self.daily_films is not None and films >= self.daily_films:
                raise SpendingCapExceeded(
                    "today's film quota is spent; try again tomorrow")
            seen = data.get("visitors", {})
            if not isinstance(seen, dict):
                raise AccountingError(
                    "spending accounting is corrupt; refusing to spend")
            count = int(seen.get(visitor, 0))
            if self.visitor_films is not None and count >= self.visitor_films:
                raise SpendingCapExceeded(
                    "this visitor's film quota is spent; try again tomorrow")
            data["films"] = films + 1
            seen[visitor] = count + 1
            data["visitors"] = seen


_DAILY: BudgetAuthority | None = None


def configure_spending(path=None, daily_cap_usd=None, daily_films=None,
                       visitor_films=None) -> None:
    """Arm the budget authority (the web entry point calls this at
    startup); a None path disarms it again."""
    global _DAILY
    _DAILY = None if path is None else BudgetAuthority(
        path, daily_cap_usd, daily_films, visitor_films)


def _usage_dict(usage) -> dict:
    if usage is None or isinstance(usage, str):
        return {}
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    else:
        prompt = getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0))
        completion = getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0))
    try:
        return {"prompt_tokens": int(prompt or 0), "completion_tokens": int(completion or 0),
                "total_tokens": int(prompt or 0) + int(completion or 0)}
    except (TypeError, ValueError):
        return {}
