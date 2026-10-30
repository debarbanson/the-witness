"""The Witness on Modal, private staging.

Allowlisted image: the witness package plus three reviewed example
films. Never out/, samples/ or .env.local. Keys arrive only as the
Modal secret "the-witness-keys". One budget authority serves every
container through a single max-concurrency-1 ledger function over a
Dict (a Dict alone is not atomic for read-modify-write; the single
container makes it so). Job state lives in a Dict, job files on a
Volume, and a daily cron enforces the 24 h retention rule.

Volume protocol: the web container commits before spawning the
worker, the worker reloads on start and commits when done, and film
asset reads reload first, so no container ever serves stale bytes.
"""

import threading

import modal

EXAMPLES = [
    {"slug": "de-adriaan", "name": "De Adriaan, Haarlem",
     "local": "out/q2763574-de-adriaan/film"},
    {"slug": "major-oak", "name": "The Major Oak, Sherwood Forest",
     "local": "out/q388443-major-oak/film"},
    {"slug": "rubjerg-knude", "name": "Rubjerg Knude lighthouse, Denmark",
     "local": "out/q2206180-rubjerg-knude-fyr/film"},
]

TRY_DAILY_CAP_USD = 5.0
TRY_DAILY_FILMS = 10
TRY_VISITOR_FILMS = 2

_LEDGER_LOCK = threading.Lock()

app = modal.App("the-witness")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(["fastapi", "python-multipart", "pillow", "openai",
                  "meta-sam-parser"])
    .add_local_dir("witness", remote_path="/app/witness")
    .add_local_dir("out/q2763574-de-adriaan/film",
                   remote_path="/app/examples/de-adriaan")
    .add_local_dir("out/q388443-major-oak/film",
                   remote_path="/app/examples/major-oak")
    .add_local_dir("out/q2206180-rubjerg-knude-fyr/film",
                   remote_path="/app/examples/rubjerg-knude")
    .env({"PYTHONPATH": "/app"})
)

keys = modal.Secret.from_name("the-witness-keys")
jobs_volume = modal.Volume.from_name("witness-jobs", create_if_missing=True)
store_dict = modal.Dict.from_name("witness-store", create_if_missing=True)
ledger_dict = modal.Dict.from_name("witness-ledger", create_if_missing=True)


@app.function(max_containers=1)
def ledger_op(op):
    """The one budget authority: serialized read-modify-write on the
    shared ledger record. Every failure mode refuses (fail closed)."""
    import json
    from datetime import date

    name = f"spending-{date.today().isoformat()}"
    with _LEDGER_LOCK:
        try:
            raw = ledger_dict.get(name, "")
            data = json.loads(raw) if raw.strip() else {}
        except (ValueError, OSError):
            return {"ok": False, "error": "accounting corrupt"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "accounting corrupt"}
        data.setdefault("total_usd", 0.0)
        data.setdefault("reserved_usd", 0.0)
        data.setdefault("calls", 0)
        data.setdefault("films", 0)
        data.setdefault("visitors", {})
        kind = op.get("kind")
        if kind == "reserve":
            ceiling = float(op["ceiling_usd"])
            cap = op.get("cap_usd")
            if (cap is not None and data["total_usd"] + data["reserved_usd"]
                    + ceiling > cap):
                return {"ok": False, "error": "cap"}
            data["reserved_usd"] += ceiling
        elif kind == "reconcile":
            data["reserved_usd"] = max(
                0.0, data["reserved_usd"] - float(op["ceiling_usd"]))
            data["total_usd"] += float(op["actual_usd"])
            data["calls"] += 1
        elif kind == "admit":
            daily, per_visitor, visitor = (op.get("daily_films"),
                                           op.get("visitor_films"),
                                           op["visitor"])
            if daily is not None and data["films"] >= daily:
                return {"ok": False, "error": "daily quota"}
            seen = data["visitors"]
            if (per_visitor is not None
                    and seen.get(visitor, 0) >= per_visitor):
                return {"ok": False, "error": "visitor quota"}
            data["films"] += 1
            seen[visitor] = seen.get(visitor, 0) + 1
        elif kind == "total":
            pass
        else:
            return {"ok": False, "error": "unknown op"}
        try:
            ledger_dict[name] = json.dumps(data)
        except OSError:
            return {"ok": False, "error": "accounting unavailable"}
        return {"ok": True, "total_usd": data["total_usd"],
                "reserved_usd": data["reserved_usd"]}


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
        self._call({"kind": "reserve", "ceiling_usd": ceiling_usd,
                    "cap_usd": self.cap_usd})
        return self._models.BudgetTicket(ceiling_usd)

    def reconcile(self, ticket, actual_usd):
        self._call({"kind": "reconcile",
                    "ceiling_usd": ticket.ceiling_usd,
                    "actual_usd": actual_usd})

    def admit(self, visitor):
        self._call({"kind": "admit", "visitor": visitor,
                    "daily_films": self.daily_films,
                    "visitor_films": self.visitor_films})

    def total_usd(self):
        return float(self._call({"kind": "total"})["total_usd"])

    def reserved_usd(self):
        return float(self._call({"kind": "total"})["reserved_usd"])


class DictStore:
    """MemoryStore protocol over a Modal Dict. No locations, no places."""

    def __init__(self, handle=None):
        self._dict = handle if handle is not None else store_dict

    def _job(self, job_id):
        try:
            return dict(self._dict[job_id])
        except KeyError:
            raise KeyError(job_id)

    def _save(self, job_id, job):
        self._dict[job_id] = job

    def create_job(self, job_id, record):
        self._dict[job_id] = record

    def get_job(self, job_id):
        return self._job(job_id)

    def set_status(self, job_id, status):
        job = self._job(job_id)
        job["status"] = status
        self._save(job_id, job)

    def append_event(self, job_id, event):
        job = self._job(job_id)
        job["events"] = job["events"] + [event]
        self._save(job_id, job)

    def set_confirm(self, job_id, confirm):
        job = self._job(job_id)
        job["confirm"] = confirm
        if confirm is not None:
            job["status"] = "confirming"
        self._save(job_id, job)

    def get_decision(self, job_id):
        return self._job(job_id)["decision"]

    def set_decision(self, job_id, confirm):
        job = self._job(job_id)
        job["decision"] = confirm
        self._save(job_id, job)

    def set_cancel(self, job_id):
        job = self._job(job_id)
        job["cancel"] = True
        if job["status"] in ("started", "confirming", "working"):
            job["status"] = "cancelled"
        self._save(job_id, job)

    def is_cancelled(self, job_id):
        return self._job(job_id)["cancel"]

    def finish_job(self, job_id, result):
        import time as _time

        job = self._job(job_id)
        job["status"] = "done"
        job["result"] = result
        job["ended_at"] = result.get("ended_at") or _time.time()
        self._save(job_id, job)

    def drop_job(self, job_id):
        try:
            del self._dict[job_id]
        except KeyError:
            pass

    def job_ids(self):
        return list(self._dict.keys())


def _worker_store():
    return DictStore(modal.Dict.from_name("witness-store"))


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume},
             timeout=1800)
def run_film(spec):
    """One Try-your-own film through the tested runner; a closed tab
    (or DELETE) cancels through the job control."""
    import threading

    from witness.webfilm import run_web_film

    jobs_volume.reload()
    job_id = spec["job_id"]
    store = _worker_store()
    authority = ModalAuthority(cap_usd=TRY_DAILY_CAP_USD,
                               daily_films=TRY_DAILY_FILMS,
                               visitor_films=TRY_VISITOR_FILMS)
    stop = threading.Event()

    def watch_cancel(control):
        def poll():
            while not stop.wait(2.0):
                try:
                    if store.is_cancelled(job_id):
                        control.cancel()
                        return
                except KeyError:
                    return

        threading.Thread(target=poll, daemon=True).start()

    try:
        outcome = run_web_film({**spec, "on_cancel": watch_cancel}, store,
                               authority)
    finally:
        stop.set()
    jobs_volume.commit()
    return outcome


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume},
             schedule=modal.Period(days=1))
def prune_daily():
    """Enforce the 24 h retention rule across job files and records."""
    import time as _time

    from witness.webapp import prune_jobs

    jobs_volume.reload()
    pruned = prune_jobs(_worker_store(), _time.time())
    jobs_volume.commit()
    return {"pruned": pruned}


CONTACT = "the studio behind this demo (contact on the hackathon page)"


@app.function(image=image, secrets=[keys], volumes={"/jobs": jobs_volume})
@modal.asgi_app()
def web():
    """The private page: examples plus Try your own."""
    import os

    from witness.webapp import WebDeps, create_app

    def spawn(spec):
        jobs_volume.commit()
        run_film.spawn(spec)

    app = create_app(WebDeps(
        store=DictStore(), authority=None, runner=spawn,
        jobs_root="/jobs", examples_root="/app/examples",
        examples=[{"slug": ex["slug"], "name": ex["name"]} for ex in EXAMPLES],
        contact=os.environ.get("WITNESS_CONTACT", CONTACT),
        secure_cookies=True))

    volume = jobs_volume

    class _Reload:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        async def __call__(self, scope, receive, send):
            if scope.get("path", "").startswith("/film/"):
                volume.reload()
            await self._wrapped(scope, receive, send)

    return _Reload(app)
