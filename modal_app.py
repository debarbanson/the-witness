"""The Witness on Modal, private staging.

Allowlisted image: the witness package plus three reviewed example
films. Never out/, samples/ or .env.local. Keys arrive only as the
Modal secret "the-witness-keys". One budget authority serves every
container through a single-container ledger function over a Dict
(a Dict alone is not atomic for read-modify-write; the single
container makes it so), and one single-container slot function
paces Nominatim to the usage policy's one request per second.
Job state lives in a Dict, job files on a Volume, and an hourly cron
enforces the 24 h retention rule.

Volume protocol: the web container commits before spawning the
worker, the worker reloads on start and commits when done, and film
asset reads reload first, so no container ever serves stale bytes.

Deploy protocol: stop the app before each deploy (modal app stop),
so the old ledger container never overlaps the new one; a Dict has
no compare-and-set. The ledger schema version fails closed when a
newer container meets an older record.
"""

import os
import threading
from pathlib import Path

import modal

from witness.webapp import MAX_FILMS_PER_DAY, MAX_VISITOR_FILMS_PER_DAY

def _available_examples(root=None):
    """Example films baked into the image when their local folders
    exist. Missing ones are skipped with a log line, so a fresh
    clone without the git-ignored films still deploys."""
    wanted = [
        ("de-adriaan", "De Adriaan, Haarlem",
         "out/q2763574-de-adriaan/film"),
        ("major-oak", "The Major Oak, Sherwood Forest",
         "out/q388443-major-oak/film"),
        ("rubjerg-knude", "Rubjerg Knude lighthouse, Denmark",
         "out/q2206180-rubjerg-knude-fyr/film"),
    ]
    base = root or Path(__file__).resolve().parent
    found = []
    for slug, name, local in wanted:
        if (base / local / "film.html").exists():
            found.append({"slug": slug, "name": name, "local": local})
        else:
            print(f"examples: skipping {slug} (no local film at {local})")
    return found


EXAMPLES = _available_examples()

TRY_DAILY_CAP_USD = 5.0
TRY_DAILY_FILMS = MAX_FILMS_PER_DAY
TRY_VISITOR_FILMS = MAX_VISITOR_FILMS_PER_DAY

LEDGER_SCHEMA = 1

_LEDGER_LOCK = threading.Lock()

app = modal.App("the-witness")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements-lock.txt")
    .add_local_dir("witness", remote_path="/app/witness")
    .env({"PYTHONPATH": "/app"})
)
for _example in EXAMPLES:
    image = image.add_local_dir(
        _example["local"],
        remote_path=f"/app/examples/{_example['slug']}")

keys = modal.Secret.from_name("the-witness-keys")
jobs_volume = modal.Volume.from_name("witness-jobs", create_if_missing=True)
store_dict = modal.Dict.from_name("witness-store", create_if_missing=True)
ledger_dict = modal.Dict.from_name("witness-ledger", create_if_missing=True)
nominatim_dict = modal.Dict.from_name("witness-nominatim", create_if_missing=True)


def _apply_ledger_op(data, op):
    """One ledger op on the loaded record. Pure and tested; the
    function below only loads, locks and saves. Returns the record
    and the answer. `extra` is a second visitor key under the same
    per-visitor quota; the film is counted once."""
    if data.get("schema", LEDGER_SCHEMA) != LEDGER_SCHEMA:
        return data, {"ok": False, "error": "accounting corrupt"}
    data.setdefault("schema", LEDGER_SCHEMA)
    data.setdefault("total_usd", 0.0)
    data.setdefault("reserved_usd", 0.0)
    data.setdefault("calls", 0)
    data.setdefault("films", 0)
    data.setdefault("visitors", {})
    data.setdefault("open", {})
    kind = op.get("kind")
    if kind == "reserve":
        ceiling = float(op["ceiling_usd"])
        cap = op.get("cap_usd")
        if (cap is not None and data["total_usd"] + data["reserved_usd"]
                + ceiling > cap):
            return data, {"ok": False, "error": "cap"}
        data["reserved_usd"] += ceiling
        data["open"][op["ticket_id"]] = ceiling
    elif kind == "reconcile":
        held = data["open"].pop(op.get("ticket_id"), None)
        if held is None:
            return data, {"ok": False, "error": "unknown ticket"}
        data["reserved_usd"] = max(0.0, data["reserved_usd"] - held)
        data["total_usd"] += float(op["actual_usd"])
        data["calls"] += 1
    elif kind == "admit":
        daily, per_visitor = op.get("daily_films"), op.get("visitor_films")
        keys = [op["visitor"]] + ([op["extra"]] if op.get("extra") else [])
        if daily is not None and data["films"] >= daily:
            return data, {"ok": False, "error": "daily quota"}
        seen = data["visitors"]
        if not isinstance(seen, dict):
            return data, {"ok": False, "error": "accounting corrupt"}
        try:
            now = float(op.get("now") or 0.0)
        except (TypeError, ValueError):
            now = 0.0

        def _count(key):
            entry = seen.get(key, 0)
            if isinstance(entry, dict):
                return int(entry.get("n", 0))
            return int(entry)  # legacy plain count

        try:
            counts = {key: _count(key) for key in keys}
        except (TypeError, ValueError):
            return data, {"ok": False, "error": "accounting corrupt"}
        for key in keys:
            if (per_visitor is not None
                    and counts[key] >= per_visitor):
                return data, {"ok": False, "error": "visitor quota"}
        data["films"] += 1
        for key in keys:
            seen[key] = {"n": counts[key] + 1, "at": now}
    elif kind == "total":
        pass
    elif kind == "reset":
        data["films"] = 0
        data["visitors"] = {}
    elif kind == "expire":
        try:
            now = float(op.get("now") or 0.0)
        except (TypeError, ValueError):
            return data, {"ok": False, "error": "accounting corrupt"}
        cutoff = now - 24 * 3600
        seen = data["visitors"]
        if not isinstance(seen, dict):
            return data, {"ok": False, "error": "accounting corrupt"}
        expired = 0
        for key in list(seen):
            entry = seen[key]
            at = entry.get("at", 0) if isinstance(entry, dict) else 0
            try:
                fresh = float(at) > cutoff
            except (TypeError, ValueError):
                fresh = False
            if not fresh:
                del seen[key]
                expired += 1
        return data, {"ok": True, "total_usd": data["total_usd"],
                      "reserved_usd": data["reserved_usd"],
                      "expired": expired}
    elif kind == "snapshot":
        seen = data["visitors"]
        return data, {"ok": True, "films": data["films"],
                      "visitors": len(seen) if isinstance(seen, dict) else 0,
                      "calls": data["calls"],
                      "total_usd": data["total_usd"],
                      "reserved_usd": data["reserved_usd"]}
    else:
        return data, {"ok": False, "error": "unknown op"}
    return data, {"ok": True, "total_usd": data["total_usd"],
                  "reserved_usd": data["reserved_usd"]}


@app.function(max_containers=1)
def ledger_op(op):
    """The one budget authority: serialized read-modify-write on the
    shared ledger record. Every failure mode refuses (fail closed)."""
    import json
    from datetime import date

    name = f"spending-{op.get('day') or date.today().isoformat()}"
    with _LEDGER_LOCK:
        try:
            raw = ledger_dict.get(name)
        except OSError:
            return {"ok": False, "error": "accounting unavailable"}
        if raw is None:
            data = {}
        elif not raw.strip():
            return {"ok": False, "error": "accounting corrupt"}
        else:
            try:
                data = json.loads(raw)
            except ValueError:
                return {"ok": False, "error": "accounting corrupt"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "accounting corrupt"}
        data, answer = _apply_ledger_op(data, op)
        if not answer.get("ok"):
            return answer
        try:
            ledger_dict[name] = json.dumps(data)
        except OSError:
            return {"ok": False, "error": "accounting unavailable"}
        return answer


class ModalAuthority:
    """BudgetAuthority protocol over the ledger function. Any error or
    refusal raises, failing closed."""

    def __init__(self, cap_usd=None, daily_films=None, visitor_films=None):
        from witness import models

        self._models = models
        self.cap_usd = cap_usd
        self.daily_films = daily_films
        self.visitor_films = visitor_films

    def _call(self, op):
        try:
            answer = ledger_op.remote(op)
        except Exception as exc:
            raise self._models.AccountingError(
                f"budget authority unreachable: {exc}")
        if not answer.get("ok"):
            if answer.get("error") in ("cap", "daily quota", "visitor quota"):
                raise self._models.SpendingCapExceeded(answer["error"])
            raise self._models.AccountingError(answer.get("error", "?"))
        return answer

    def reserve(self, ceiling_usd):
        from datetime import date as _date

        ticket = self._models.BudgetTicket(
            ceiling_usd, account=f"spending-{_date.today().isoformat()}")
        self._call({"kind": "reserve", "ticket_id": ticket.ticket_id,
                    "ceiling_usd": ceiling_usd, "cap_usd": self.cap_usd,
                    "day": ticket.account.removeprefix("spending-")})
        return ticket

    def reconcile(self, ticket, actual_usd):
        day = ((ticket.account or "").removeprefix("spending-")
               or None)
        self._call({"kind": "reconcile", "ticket_id": ticket.ticket_id,
                    "actual_usd": actual_usd, "day": day})

    def admit(self, visitor, extra=None):
        import time as _time

        self._call({"kind": "admit", "visitor": visitor, "extra": extra,
                    "daily_films": self.daily_films,
                    "visitor_films": self.visitor_films,
                    "now": _time.time()})

    def total_usd(self):
        return float(self._call({"kind": "total"})["total_usd"])

    def reserved_usd(self):
        return float(self._call({"kind": "total"})["reserved_usd"])

    def reset_quotas(self):
        """Clear the film and visitor counters, keeping spend. Only the
        staging abuse reset calls this, between cases."""
        self._call({"kind": "reset"})

    def snapshot(self):
        """Counts only, never visitor keys."""
        answer = self._call({"kind": "snapshot"})
        return {"films": int(answer["films"]),
                "visitors": int(answer["visitors"]),
                "calls": int(answer["calls"]),
                "total_usd": float(answer["total_usd"]),
                "reserved_usd": float(answer["reserved_usd"])}


class DictStore:
    """MemoryStore protocol over a Modal Dict. No locations, no places.

    One key per field: the worker's progress writes can never clobber
    the web container's cancel flag or decision, and back. A single
    Dict put is the atomic unit; whole-record read-modify-write is
    gone. Appended events can still race each other (two workers
    never share a job, so only a retry overlaps), losing at most a
    progress line, never a flag.
    """

    _FIELDS = ("meta", "status", "events", "confirm", "decision",
               "cancel", "result", "ended", "poll")

    def __init__(self, handle=None):
        self._dict = handle if handle is not None else store_dict

    def _key(self, job_id, field):
        return f"{job_id}:{field}"

    def _meta(self, job_id):
        try:
            return dict(self._dict[self._key(job_id, "meta")])
        except KeyError:
            raise KeyError(job_id)

    def _field(self, job_id, field, default):
        try:
            return self._dict[self._key(job_id, field)]
        except KeyError:
            return default

    def create_job(self, job_id, record):
        meta = {key: record.get(key) for key in
                ("vid", "vkey", "token", "job_dir", "started_at")}
        self._dict[self._key(job_id, "meta")] = meta
        self._dict[self._key(job_id, "status")] = record.get("status",
                                                             "started")
        self._dict[self._key(job_id, "events")] = list(
            record.get("events", []))
        self._dict[self._key(job_id, "confirm")] = record.get("confirm")
        self._dict[self._key(job_id, "decision")] = record.get("decision")
        self._dict[self._key(job_id, "cancel")] = bool(
            record.get("cancel", False))
        self._dict[self._key(job_id, "result")] = record.get("result")
        self._dict[self._key(job_id, "ended")] = record.get("ended_at")
        self._dict[self._key(job_id, "poll")] = record.get(
            "last_poll", record.get("started_at", 0.0))

    def get_job(self, job_id):
        meta = self._meta(job_id)
        return {"vid": meta.get("vid"), "vkey": meta.get("vkey"),
                "token": meta.get("token"), "job_dir": meta.get("job_dir"),
                "started_at": meta.get("started_at", 0.0),
                "status": self._field(job_id, "status", "started"),
                "events": self._field(job_id, "events", []),
                "confirm": self._field(job_id, "confirm", None),
                "decision": self._field(job_id, "decision", None),
                "cancel": self._field(job_id, "cancel", False),
                "result": self._field(job_id, "result", None),
                "ended_at": self._field(job_id, "ended", None),
                "last_poll": self._field(job_id, "poll",
                                          meta.get("started_at", 0.0))}

    def set_status(self, job_id, status):
        self._meta(job_id)
        self._dict[self._key(job_id, "status")] = status

    def append_event(self, job_id, event):
        self._meta(job_id)
        key = self._key(job_id, "events")
        try:
            events = list(self._dict[key])
        except KeyError:
            events = []
        self._dict[key] = events + [event]

    def set_confirm(self, job_id, confirm):
        self._meta(job_id)
        self._dict[self._key(job_id, "confirm")] = confirm
        if confirm is not None:
            self._dict[self._key(job_id, "status")] = "confirming"

    def get_decision(self, job_id):
        self._meta(job_id)
        return self._field(job_id, "decision", None)

    def set_decision(self, job_id, confirm):
        self._meta(job_id)
        self._dict[self._key(job_id, "decision")] = confirm

    def set_cancel(self, job_id):
        import time as _time

        self._meta(job_id)
        self._dict[self._key(job_id, "cancel")] = True
        if self._field(job_id, "ended", None) is None:
            self._dict[self._key(job_id, "ended")] = _time.time()
        if self._field(job_id, "status", "started") in (
                "started", "confirming", "working"):
            self._dict[self._key(job_id, "status")] = "cancelled"

    def is_cancelled(self, job_id):
        self._meta(job_id)
        return self._field(job_id, "cancel", False)

    def touch(self, job_id):
        import time as _time

        self._meta(job_id)
        self._dict[self._key(job_id, "poll")] = _time.time()

    def last_poll(self, job_id):
        meta = self._meta(job_id)
        return self._field(job_id, "poll", meta.get("started_at", 0.0))

    def end_job(self, job_id, status, result):
        import time as _time

        self._meta(job_id)
        self._dict[self._key(job_id, "status")] = status
        self._dict[self._key(job_id, "result")] = result
        self._dict[self._key(job_id, "ended")] = (
            result.get("ended_at") or _time.time())

    def finish_job(self, job_id, result):
        self.end_job(job_id, "done", result)

    def drop_job(self, job_id):
        for field in self._FIELDS:
            try:
                del self._dict[self._key(job_id, field)]
            except KeyError:
                pass

    def job_ids(self):
        return sorted(key[:-5] for key in self._dict.keys()
                      if key.endswith(":meta"))


def _worker_store():
    return DictStore(modal.Dict.from_name("witness-store"))


def _contact():
    """The page's contact, from the secret. Refusing to start without
    a real address: the notice names this contact."""
    try:
        return os.environ["WITNESS_CONTACT"]
    except KeyError:
        raise RuntimeError("WITNESS_CONTACT is not set: the page needs "
                           "a real contact before it goes live")


def _ip_secret():
    """The shared visitor-hash secret, from the secret. One value for
    every container, derived per day in visitor_key, so every
    container hashes an address the same way. Refusing to start
    without it: a per-container secret would let a fresh cookie
    bypass the visitor quota."""
    try:
        return os.environ["WITNESS_IP_SECRET"]
    except KeyError:
        raise RuntimeError("WITNESS_IP_SECRET is not set: the page needs "
                           "a shared visitor-hash secret before it goes live")


def _watch_job(store, job_id, control, stop, poll_s=2.0, heartbeat_s=120,
               now=None):
    """Cancel the job when the visitor cancels or the tab goes quiet:
    no poll for `heartbeat_s` seconds means a closed tab."""
    import time as _time

    tick = now or _time.time

    def poll():
        while not stop.wait(poll_s):
            try:
                if store.is_cancelled(job_id):
                    control.cancel()
                    return
                if tick() - store.last_poll(job_id) > heartbeat_s:
                    control.cancel()
                    return
            except KeyError:
                return

    threading.Thread(target=poll, daemon=True).start()


def _nominatim_wait(last_fired, now) -> float:
    """Seconds to wait before the next Nominatim call: the usage
    policy allows one request per second per application
    (https://operations.osmfoundation.org/policies/nominatim/)."""
    return max(0.0, 1.0 - (now - last_fired))


_NOMINATIM_LOCK = threading.Lock()


@app.function(max_containers=1)
def nominatim_slot():
    """One limiter shared across containers: a single container plus
    a lock and the last-fired timestamp in the Dict paces every
    Nominatim call to at most one per second, however many workers
    run."""
    import time as _time

    with _NOMINATIM_LOCK:
        try:
            last = float(nominatim_dict.get("last", 0.0))
        except (KeyError, ValueError, TypeError):
            last = 0.0
        wait = _nominatim_wait(last, _time.time())
        if wait:
            _time.sleep(wait)
        nominatim_dict["last"] = _time.time()
    return True


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume},
             timeout=1800)
def run_film(ref):
    """One Try-your-own film through the tested runner; a closed tab
    (or DELETE) cancels through the job control. `ref` carries only
    the job id and folder: the place and location stay in the job's
    private spec file, never in spawn arguments or logs. The file is
    scrubbed as soon as it is read, before any paid call."""
    from witness.webfilm import load_spec, run_web_film, scrub_hand_off

    jobs_volume.reload()
    job_id = ref["job_id"]
    store = _worker_store()
    try:
        spec = load_spec(ref["job_dir"])
    except (OSError, ValueError) as exc:
        try:
            store.end_job(
                job_id, "failed",
                {"message": f"broken job spec: {exc.__class__.__name__}"})
        except KeyError:
            pass
        jobs_volume.commit()
        return {"status": "failed"}
    scrub_hand_off(ref["job_dir"])
    jobs_volume.commit()
    authority = ModalAuthority(cap_usd=TRY_DAILY_CAP_USD,
                               daily_films=TRY_DAILY_FILMS,
                               visitor_films=TRY_VISITOR_FILMS)
    stop = threading.Event()

    def watch_cancel(control):
        _watch_job(store, job_id, control, stop)

    def nominatim_pace():
        nominatim_slot.remote()

    try:
        outcome = run_web_film({**spec, "on_cancel": watch_cancel}, store,
                               authority, nominatim_pace=nominatim_pace)
    finally:
        stop.set()
    jobs_volume.commit()
    return outcome


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume},
             schedule=modal.Period(hours=1))
def prune_hourly():
    """Enforce the 24 h retention rule across job files and records,
    sweep job folders the store no longer knows, and expire visitor
    hashes in the ledger (the totals stay). A failed ledger scrub
    heals on the next hour."""
    import time as _time
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    from witness.webapp import prune_jobs, sweep_job_dirs

    jobs_volume.reload()
    store = _worker_store()
    now = _time.time()
    pruned = prune_jobs(store, now)
    swept = sweep_job_dirs(store, "/jobs", now)
    jobs_volume.commit()
    expired = 0
    today = _date.today()
    for back in range(8):
        day = (today - _timedelta(days=back)).isoformat()
        if back < 2:
            try:
                answer = ledger_op.remote({"kind": "expire", "now": now,
                                           "day": day})
            except Exception:
                continue
            if answer.get("ok"):
                expired += int(answer.get("expired", 0))
        else:
            ledger_dict.pop(f"spending-{day}", None)
    return {"pruned": pruned, "swept": swept, "expired": expired}


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume})
@modal.asgi_app(requires_proxy_auth=True)
def web():
    """The private page: examples plus Try your own. Proxy auth keeps
    staging off the public internet (Modal proxy-auth docs:
    https://modal.com/docs/guide/webhook-proxy-auth)."""
    from witness.webapp import WebDeps, create_app

    def spawn(ref):
        jobs_volume.commit()
        return run_film.spawn(ref)

    app = create_app(WebDeps(
        store=DictStore(),
        authority=ModalAuthority(cap_usd=TRY_DAILY_CAP_USD,
                                 daily_films=TRY_DAILY_FILMS,
                                 visitor_films=TRY_VISITOR_FILMS),
        runner=spawn,
        jobs_root="/jobs", examples_root="/app/examples",
        examples=[{"slug": ex["slug"], "name": ex["name"]} for ex in EXAMPLES],
        contact=_contact(),
        secure_cookies=True,
        ip_secret=_ip_secret(),
        debug_reset=os.environ.get("WITNESS_ABUSE_RESET") == "1"))

    volume = jobs_volume

    class _Reload:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        async def __call__(self, scope, receive, send):
            if scope.get("path", "").startswith("/film/"):
                volume.reload()
            await self._wrapped(scope, receive, send)

    return _Reload(app)
