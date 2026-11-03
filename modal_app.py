"""The Witness on Modal: private staging plus public judge mode.

Allowlisted image: the witness package only. Never out/, samples/
or .env.local. The reviewed example films live on a shared Volume,
read when each app instance starts. Keys arrive only as the
Modal secret "the-witness-keys". One budget authority serves every
container through a single-container ledger function over a Dict
(a Dict alone is not atomic for read-modify-write; the single
container makes it so), and one single-container slot function
paces Nominatim to the usage policy's one request per second.
Job state lives in a Dict, job files on a Volume, and an hourly cron
enforces the 24 h retention rule. Staging (`web`, proxy auth) and
judge mode (`judge`, public and unlisted) run on fully separate
state. Both serve the reviewed examples from the shared Volume;
judge mode gates Try your own behind a hard cap, quotas and an
off switch.

Volume protocol: the web container commits before spawning the
worker, the worker reloads on start and commits when done, and film
asset reads reload first, so no container ever serves stale bytes.

Deploy protocol: drain running films, then stop the app before
each deploy (modal app stop), so the old ledger container never
overlaps the new one; a Dict has no compare-and-set. The ledger
schema version fails closed when a newer container meets an older
record.
"""

import os
import threading
from pathlib import Path

import modal

from witness.webapp import (MAX_FILMS_PER_DAY, MAX_NETWORK_FILMS_PER_DAY,
                            MAX_VISITOR_FILMS_PER_DAY)

TRY_DAILY_CAP_USD = 10.0
TRY_DAILY_FILMS = MAX_FILMS_PER_DAY
TRY_VISITOR_FILMS = MAX_VISITOR_FILMS_PER_DAY
TRY_NETWORK_FILMS = MAX_NETWORK_FILMS_PER_DAY

LEDGER_SCHEMA = 1

_LEDGER_LOCK = threading.Lock()

app = modal.App("the-witness")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements-lock.txt")
    .env({"PYTHONPATH": "/app"})
    .add_local_dir("witness", remote_path="/app/witness")
)

keys = modal.Secret.from_name("the-witness-keys")
jobs_volume = modal.Volume.from_name("witness-jobs", create_if_missing=True)
store_dict = modal.Dict.from_name("witness-store", create_if_missing=True)
ledger_dict = modal.Dict.from_name("witness-ledger", create_if_missing=True)
nominatim_dict = modal.Dict.from_name("witness-nominatim", create_if_missing=True)
# Judge mode runs on fully separate state, so staging tests can never
# spend the judging budget or reset its quotas.
judge_jobs_volume = modal.Volume.from_name("witness-judge-jobs",
                                           create_if_missing=True)
judge_store_dict = modal.Dict.from_name("witness-judge-store",
                                        create_if_missing=True)
judge_ledger_dict = modal.Dict.from_name("witness-judge-ledger",
                                         create_if_missing=True)
try_flag_dict = modal.Dict.from_name("witness-judge-flag",
                                     create_if_missing=True)
examples_volume = modal.Volume.from_name("witness-examples",
                                         create_if_missing=True)


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
        daily = op.get("daily_films")
        per_visitor = op.get("visitor_films")
        per_network = op.get("network_films", per_visitor)
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
        if (per_visitor is not None
                and counts[op["visitor"]] >= per_visitor):
            return data, {"ok": False, "error": "visitor quota"}
        if (op.get("extra") and per_network is not None
                and counts[op["extra"]] >= per_network):
            return data, {"ok": False, "error": "network quota"}
        data["films"] += 1
        for key in keys:
            seen[key] = {"n": counts[key] + 1, "at": now}
    elif kind == "release":
        keys = [op["visitor"]] + ([op["extra"]] if op.get("extra") else [])
        seen = data["visitors"]
        if not isinstance(seen, dict):
            return data, {"ok": False, "error": "accounting corrupt"}
        data["films"] = max(0, int(data.get("films", 0)) - 1)
        for key in keys:
            entry = seen.get(key)
            if entry is None:
                continue
            if isinstance(entry, dict):
                try:
                    n = int(entry.get("n", 0))
                except (TypeError, ValueError):
                    return data, {"ok": False, "error": "accounting corrupt"}
                seen[key] = {"n": max(0, n - 1),
                             "at": entry.get("at", 0)}
            else:
                try:
                    n = int(entry)
                except (TypeError, ValueError):
                    return data, {"ok": False, "error": "accounting corrupt"}
                seen[key] = max(0, n - 1)
    elif kind == "total":
        pass
    elif kind == "quota":
        seen = data["visitors"]
        if not isinstance(seen, dict):
            return data, {"ok": False, "error": "accounting corrupt"}

        def _count(key):
            entry = seen.get(key, 0)
            if isinstance(entry, dict):
                return int(entry.get("n", 0))
            return int(entry)

        try:
            visitor_used = _count(op.get("visitor", ""))
            extra = op.get("extra")
            network_used = _count(extra) if extra else 0
        except (TypeError, ValueError):
            return data, {"ok": False, "error": "accounting corrupt"}
        return data, {"ok": True, "films": int(data.get("films", 0)),
                      "visitor": visitor_used, "network": network_used}
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


def _ledger_for(backend):
    """The ledger Dict for a backend, or None for an unknown one."""
    if backend == "judge":
        return judge_ledger_dict
    if backend in (None, "staging"):
        return ledger_dict
    return None


@app.function(image=image, max_containers=1)
def ledger_op(op):
    """The one budget authority: serialized read-modify-write on the
    shared ledger record. Every failure mode refuses (fail closed)."""
    import json
    from datetime import date

    handle = _ledger_for(op.get("backend", "staging"))
    if handle is None:
        return {"ok": False, "error": "unknown backend"}
    name = f"spending-{op.get('day') or date.today().isoformat()}"
    with _LEDGER_LOCK:
        try:
            raw = handle.get(name)
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
            handle[name] = json.dumps(data)
        except OSError:
            return {"ok": False, "error": "accounting unavailable"}
        return answer


class ModalAuthority:
    """BudgetAuthority protocol over the ledger function. Any error or
    refusal raises, failing closed."""

    def __init__(self, cap_usd=None, daily_films=None, visitor_films=None,
                 backend="staging", network_films=None):
        from witness import models

        self._models = models
        self.cap_usd = cap_usd
        self.daily_films = daily_films
        self.visitor_films = visitor_films
        self.network_films = (network_films if network_films is not None
                              else visitor_films)
        self.backend = backend

    def _call(self, op):
        op = dict(op)
        op["backend"] = self.backend
        try:
            answer = ledger_op.remote(op)
        except Exception as exc:
            raise self._models.AccountingError(
                f"budget authority unreachable: {exc}")
        if not answer.get("ok"):
            if answer.get("error") in ("cap", "daily quota", "visitor quota",
                                       "network quota"):
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
                    "network_films": self.network_films,
                    "now": _time.time()})

    def release(self, visitor, extra=None):
        """Refund one admission after a spawn that never started its
        job. Best effort: a failed refund keeps the quota spent
        rather than risking double spend."""
        try:
            self._call({"kind": "release", "visitor": visitor,
                        "extra": extra})
        except Exception:
            pass

    def quota(self, visitor, extra=None):
        """Used counts for one visitor's own keys: total films today
        plus the browser and network counts. Only the caller's own
        keys, never the whole table."""
        answer = self._call({"kind": "quota", "visitor": visitor,
                             "extra": extra})
        return {"films": int(answer.get("films", 0)),
                "visitor": int(answer.get("visitor", 0)),
                "network": int(answer.get("network", 0))}

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


def _worker_store(backend="staging"):
    if backend == "judge":
        return DictStore(modal.Dict.from_name("witness-judge-store",
                                              create_if_missing=True))
    return DictStore(modal.Dict.from_name("witness-store",
                                          create_if_missing=True))


def _contact():
    """The page's contact, from the secret. Refusing to start without
    a real address: the notice names this contact."""
    try:
        contact = os.environ["WITNESS_CONTACT"]
    except KeyError:
        raise RuntimeError("WITNESS_CONTACT is not set: the page needs "
                           "a real contact before it goes live")
    if not contact.strip():
        raise RuntimeError("WITNESS_CONTACT is blank: the page needs "
                           "a real contact before it goes live")
    return contact


def _ip_secret():
    """The shared visitor-hash secret, from the secret. One value for
    every container, derived per day in visitor_key, so every
    container hashes an address the same way. Refusing to start
    without it: a per-container secret would let a fresh cookie
    bypass the visitor quota. Blank or short values are refused;
    the real one is 64 hex characters."""
    try:
        secret = os.environ["WITNESS_IP_SECRET"]
    except KeyError:
        raise RuntimeError("WITNESS_IP_SECRET is not set: the page needs "
                           "a shared visitor-hash secret before it goes live")
    if len(secret.strip()) < 32:
        raise RuntimeError("WITNESS_IP_SECRET is blank or too short: "
                           "the page needs at least 32 characters")
    return secret


def _judge_cap() -> float:
    """Judge mode's hard daily spending cap in dollars, from the
    secret. Refusing to start without a positive number: public
    generation never runs uncapped."""
    import math

    try:
        cap = float(os.environ["WITNESS_JUDGE_CAP_USD"])
    except (KeyError, ValueError):
        raise RuntimeError("WITNESS_JUDGE_CAP_USD is not set: judge mode "
                           "needs a hard daily spending cap before it "
                           "goes live")
    if not (math.isfinite(cap) and cap > 0):
        raise RuntimeError("WITNESS_JUDGE_CAP_USD must be a positive "
                           "number of dollars")
    return cap


def _limit_setting(name: str, default: int) -> int:
    """One film limit from the secret, or the default when unset. A
    present but blank, zero, negative or non-integer value refuses
    startup, the same as the other secrets."""
    if name not in os.environ:
        return default
    raw = os.environ[name].strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a positive whole number "
                           "of films")
    if not raw.isdigit() or value <= 0:
        raise RuntimeError(f"{name} must be a positive whole number "
                           "of films")
    return value


def _daily_films() -> int:
    return _limit_setting("WITNESS_DAILY_FILMS", TRY_DAILY_FILMS)


def _visitor_films() -> int:
    return _limit_setting("WITNESS_VISITOR_FILMS", TRY_VISITOR_FILMS)


def _network_films() -> int:
    return _limit_setting("WITNESS_NETWORK_FILMS", TRY_NETWORK_FILMS)


def _check_judge_flags() -> None:
    """Refuse test flags on judge mode. The staging abuse run sets
    them in the shared secret, which the shared worker also reads,
    so judge mode refuses to start while either is set."""
    if os.environ.get("WITNESS_FAKE_PROVIDER"):
        raise RuntimeError("WITNESS_FAKE_PROVIDER is set: judge mode "
                           "never runs with test providers")
    if os.environ.get("WITNESS_ABUSE_RESET"):
        raise RuntimeError("WITNESS_ABUSE_RESET is set: judge mode "
                           "never runs with test flags")


def _try_enabled() -> bool:
    """The Try-your-own off switch, read live on every upload: the
    flag is off within a minute of the flip, with no redeploy. An
    unreadable flag fails closed: new uploads refuse, while the
    examples keep playing."""
    try:
        return try_flag_dict.get("enabled", True) is not False
    except Exception:
        return False


def _volume_examples(root):
    """Example films served from the shared Volume: the reviewed
    films uploaded once, not baked into the image. Missing ones are
    skipped with a log line."""
    catalog = (("de-adriaan", "De Adriaan, Haarlem"),
               ("major-oak", "The Major Oak, Sherwood Forest"),
               ("rubjerg-knude", "Rubjerg Knude lighthouse, Denmark"))
    found = []
    for slug, name in catalog:
        if (Path(root) / slug / "film.html").exists():
            found.append({"slug": slug, "name": name})
        else:
            print(f"examples: skipping {slug} (no film at {root}/{slug})")
    return found


def _watch_job(store, job_id, control, stop, poll_s=2.0):
    """Cancel the job when the visitor cancels. A quiet tab never
    cancels: a locked phone keeps its film, and the job runs until
    its total deadline."""
    def poll():
        while not stop.wait(poll_s):
            try:
                if store.is_cancelled(job_id):
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


@app.function(image=image, max_containers=1)
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


@app.function(image=image, secrets=[keys],
             volumes={"/jobs": jobs_volume,
                     "/judge-jobs": judge_jobs_volume},
             timeout=1800, max_containers=2, max_inputs=1)
def run_film(ref):
    """One Try-your-own film through the tested runner; only DELETE
    cancels through the job control. `ref` carries only
    the job id, folder and backend: the place and location stay in
    the job's private spec file, never in spawn arguments or logs.
    The file is scrubbed as soon as it is read, before any paid
    call. Staging and judge mode run on separate state."""
    from witness.webfilm import load_spec, run_web_film, scrub_hand_off

    backend = ref.get("backend", "staging")
    if backend == "judge":
        if os.environ.get("WITNESS_FAKE_PROVIDER"):
            store = _worker_store("judge")
            try:
                store.end_job(ref["job_id"], "failed",
                              {"message": "judge mode never runs "
                                          "with test providers"})
            except KeyError:
                pass
            return {"status": "failed"}
        volume = judge_jobs_volume
        cap_usd = _judge_cap()
    elif backend == "staging":
        volume = jobs_volume
        cap_usd = TRY_DAILY_CAP_USD
    else:
        store = _worker_store()
        try:
            store.end_job(ref["job_id"], "failed",
                          {"message": "unknown backend"})
        except KeyError:
            pass
        return {"status": "failed"}
    volume.reload()
    job_id = ref["job_id"]
    store = _worker_store(backend)
    try:
        spec = load_spec(ref["job_dir"])
    except (OSError, ValueError) as exc:
        try:
            store.end_job(
                job_id, "failed",
                {"message": f"broken job spec: {exc.__class__.__name__}"})
        except KeyError:
            pass
        volume.commit()
        return {"status": "failed"}
    scrub_hand_off(ref["job_dir"])
    volume.commit()
    authority = ModalAuthority(cap_usd=cap_usd,
                               daily_films=_daily_films(),
                               visitor_films=_visitor_films(),
                               backend=backend,
                               network_films=_network_films())
    stop = threading.Event()

    def watch_cancel(control):
        _watch_job(store, job_id, control, stop)

    def nominatim_pace():
        nominatim_slot.remote()

    try:
        outcome = run_web_film({**spec, "on_cancel": watch_cancel}, store,
                               authority, nominatim_pace=nominatim_pace,
                               commit=volume.commit)
    finally:
        stop.set()
    volume.commit()
    return outcome


@app.function(image=image, secrets=[keys],
             volumes={"/jobs": jobs_volume,
                      "/judge-jobs": judge_jobs_volume},
             schedule=modal.Cron("0 * * * *"))
def prune_hourly():
    """Enforce the 24 h retention rule across job files and records,
    sweep job folders the store no longer knows, and expire visitor
    hashes in the ledger (the totals stay). A failed ledger scrub
    heals on the next hour. Each backend reloads, deletes, commits
    and drops on its own, so one backend's failure never skips the
    other's cleanup; records are dropped only after their volume
    commit succeeds. The first backend error surfaces after both
    were attempted."""
    import time as _time
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    from witness.webapp import prune_jobs, sweep_job_dirs

    now = _time.time()
    pruned, swept, errors = 0, 0, []
    for backend, volume, jobs_root in (
            ("staging", jobs_volume, "/jobs"),
            ("judge", judge_jobs_volume, "/judge-jobs")):
        try:
            volume.reload()
            store = _worker_store(backend)
            pruned += prune_jobs(store, now, commit=volume.commit)
            swept += sweep_job_dirs(store, jobs_root, now)
            volume.commit()
        except Exception as exc:
            print(f"prune_hourly: {backend} failed: {exc}")
            errors.append(exc)
    expired = 0
    today = _date.today()
    for backend, handle in (("staging", ledger_dict),
                            ("judge", judge_ledger_dict)):
        for back in range(8):
            day = (today - _timedelta(days=back)).isoformat()
            if back < 2:
                try:
                    answer = ledger_op.remote({"kind": "expire", "now": now,
                                               "day": day,
                                               "backend": backend})
                except Exception:
                    continue
                if answer.get("ok"):
                    expired += int(answer.get("expired", 0))
            else:
                handle.pop(f"spending-{day}", None)
    print(f"prune_hourly: pruned={pruned} swept={swept} expired={expired}")
    if errors:
        raise errors[0]
    return {"pruned": pruned, "swept": swept, "expired": expired}


@app.function(image=image)
def try_switch(enable: bool):
    """Flip judge mode's Try-your-own switch, on or off within a
    minute, with no redeploy. Run from a shell with Modal access:
    modal run modal_app.py::try_switch --no-enable (off) or
    --enable (on). The examples are unaffected either way."""
    try_flag_dict["enabled"] = bool(enable)
    return {"enabled": bool(enable)}


@app.function(image=image, secrets=[keys],
             volumes={"/jobs": jobs_volume,
                     "/examples": examples_volume},
             memory=2048,  # 4 upload slots times ~200 MB per 25 MP decode
             max_containers=2)
@modal.asgi_app(requires_proxy_auth=True)
def web():
    """The private page: examples plus Try your own. Proxy auth keeps
    staging off the public internet (Modal proxy-auth docs:
    https://modal.com/docs/guide/webhook-proxy-auth). Examples are
    read from the shared Volume when the app instance starts; upload
    them before deploying, or redeploy after uploading."""
    from witness.webapp import WebDeps, create_app

    def spawn(ref):
        jobs_volume.commit()
        return run_film.spawn({**ref, "backend": "staging"})

    app = create_app(WebDeps(
        store=DictStore(),
        authority=ModalAuthority(cap_usd=TRY_DAILY_CAP_USD,
                                 daily_films=_daily_films(),
                                 visitor_films=_visitor_films(),
                                 network_films=_network_films()),
        runner=spawn,
        jobs_root="/jobs", examples_root="/examples",
        examples=_volume_examples("/examples"),
        contact=_contact(),
        secure_cookies=True,
        ip_secret=_ip_secret(),
        debug_reset=os.environ.get("WITNESS_ABUSE_RESET") == "1"))

    volume = jobs_volume
    shared = examples_volume

    class _Reload:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        async def __call__(self, scope, receive, send):
            path = scope.get("path", "")
            if path.startswith("/film/"):
                volume.reload()
            elif path.startswith("/examples/"):
                shared.reload()
            await self._wrapped(scope, receive, send)

    return _Reload(app)


@app.function(image=image, secrets=[keys],
              volumes={"/judge-jobs": judge_jobs_volume,
                      "/examples": examples_volume},
              memory=2048,  # same upload gate as staging
              max_containers=2)
@modal.asgi_app()
def judge():
    """Judge mode: the public, unlisted page. No proxy auth; the link
    goes in the README, and every response carries
    noindex. Reviewed examples come first; Try your own runs behind
    the hard daily cap, the per-visitor and global quotas, and the
    off switch. Separate state from staging throughout, and the
    abuse reset is never wired here."""
    _check_judge_flags()
    from witness.webapp import WebDeps, create_app

    def spawn(ref):
        judge_jobs_volume.commit()
        return run_film.spawn({**ref, "backend": "judge"})

    app = create_app(WebDeps(
        store=DictStore(judge_store_dict),
        authority=ModalAuthority(cap_usd=_judge_cap(),
                                 daily_films=_daily_films(),
                                 visitor_films=_visitor_films(),
                                 backend="judge",
                                 network_films=_network_films()),
        runner=spawn,
        jobs_root="/judge-jobs", examples_root="/examples",
        examples=_volume_examples("/examples"),
        contact=_contact(),
        secure_cookies=True,
        ip_secret=_ip_secret(),
        debug_reset=False,
        try_enabled=_try_enabled,
        noindex=True))

    volume = judge_jobs_volume
    shared = examples_volume

    class _Reload:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        async def __call__(self, scope, receive, send):
            path = scope.get("path", "")
            if path.startswith("/film/"):
                volume.reload()
            elif path.startswith("/examples/"):
                shared.reload()
            await self._wrapped(scope, receive, send)

    return _Reload(app)
