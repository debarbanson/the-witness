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


RESEARCH = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    timeout=300,  # web research with reasoning runs for minutes
)

VISION = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
)

VERIFY = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
    temperature=0,  # probed 27 Oct: accepted; seed is not in the SDK surface
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
)

# Steps 1 and 6: segmentation, same key as everything Meta.
SAM = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="sam-3.1",
    key_name="MODEL_API_KEY",
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
)


_CLIENTS = {}


def client_for(spec, environ=None):
    """One OpenAI-compatible client per spec and key, shared by every
    call. Key never leaves the environment."""
    from openai import OpenAI

    env = environ if environ is not None else os.environ
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


def _paid_call(spec, response):
    """Record one finished paid call on the job and daily ledgers."""
    usage = getattr(response, "usage", None) if not isinstance(response, dict) else response.get("usage")
    searches = 0 if spec.provider == "baseten" else _count_searches(response)
    cost = current_ledger().note(spec.provider, spec.model, usage, searches=searches)
    if _DAILY is not None:
        _DAILY.record(cost)
    return response


def respond(client, spec, **kwargs):
    """One Responses call: model id, reasoning effort and temperature
    injected. The daily cap is checked first; failures record nothing."""
    if spec.effort is not None:
        kwargs["reasoning"] = {"effort": spec.effort}
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    if _DAILY is not None:
        _DAILY.check()
    return _paid_call(spec, client.responses.create(model=spec.model, **kwargs))


def chat(client, spec, messages, **kwargs):
    """One Chat Completions call (the Baseten path): model id and
    temperature injected. No reasoning control: Muse Spark Open always
    reasons; read the answer with chat_answer. The daily cap is
    checked first; failures record nothing."""
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    if _DAILY is not None:
        _DAILY.check()
    return _paid_call(
        spec, client.chat.completions.create(model=spec.model, messages=messages, **kwargs))


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

    def note(self, provider, model, usage, searches=0) -> float:
        """Record one call; returns its cost in dollars."""
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
    """A fresh per-visitor ledger for one job. Worker threads inherit
    it only through submit_context."""
    token = _JOB_LEDGER.set(SpendingLedger())
    try:
        yield _JOB_LEDGER.get()
    finally:
        _JOB_LEDGER.reset(token)


def with_job_ledger(fn):
    """Run a job entry point under a fresh per-visitor ledger."""
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
    _JOB_LEDGER.set(SpendingLedger())


def note_usage(provider: str, usage, model=None) -> None:
    """Add one call's token counts to this job's running totals."""
    current_ledger().note(provider, model, usage)


def usage_totals() -> dict:
    ledger = current_ledger()
    return {provider: dict(totals) for provider, totals in ledger.totals.items()}


def current_cost_usd() -> float:
    """This job's spend so far in dollars."""
    return current_ledger().cost_usd


class DailyCap:
    """Hard daily spend ceiling, shared by every visitor. One JSON
    file per day, flock-guarded for a single machine. Multi-container
    deployments need shared storage (a Modal Dict) instead; two calls
    racing the same check can overrun by one call's cost."""

    def __init__(self, path, cap_usd=None):
        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cap_usd = cap_usd

    def _file(self):
        return self.dir / f"spending-{date.today().isoformat()}.json"

    def _locked(self):
        handle = open(self._file(), "a+")
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    def total_usd(self) -> float:
        if not self._file().exists():
            return 0.0
        handle = self._locked()
        try:
            handle.seek(0)
            try:
                return float(json.load(handle).get("total_usd", 0.0))
            except (json.JSONDecodeError, ValueError):
                return 0.0
        finally:
            handle.close()

    def check(self) -> None:
        """Raise before a paid call when the day is spent."""
        if self.cap_usd is not None and self.total_usd() >= self.cap_usd:
            raise SpendingCapExceeded(
                f"daily spending cap reached (${self.cap_usd:.2f}); "
                f"try again tomorrow")

    def record(self, cost_usd: float) -> None:
        handle = self._locked()
        try:
            handle.seek(0)
            try:
                data = json.load(handle)
            except (json.JSONDecodeError, ValueError):
                data = {}
            data["date"] = date.today().isoformat()
            data["total_usd"] = float(data.get("total_usd", 0.0)) + cost_usd
            data["calls"] = int(data.get("calls", 0)) + 1
            handle.seek(0)
            handle.truncate()
            json.dump(data, handle)
        finally:
            handle.close()


_DAILY: DailyCap | None = None


def configure_spending(path=None, daily_cap_usd=None) -> None:
    """Arm the daily cap (the web entry point calls this at startup);
    a None path disarms it again."""
    global _DAILY
    _DAILY = None if path is None else DailyCap(path, daily_cap_usd)


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
