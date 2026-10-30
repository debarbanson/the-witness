"""The private web page: upload, progress, capability films.

One FastAPI app serves the pages, the same-origin API and the film
assets. Everything Modal-specific (spawn, Dict, Volume, cron) lives
in modal_app.py; this module takes plain dependencies so the whole
page is testable offline with a fake runner and clock.

Privacy shape: the upload's location travels to the runner in memory
only and is never stored; the typed place likewise. Job films are
served only through unguessable capability URLs. Nothing request- or
location-shaped is ever logged here.
"""

import hashlib
import json
import secrets
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from witness import models, photo as photo_module
from witness.cli import job_dir
from witness.identify import IdentifyError, checked_location

RETENTION_SECONDS = 24 * 3600
MAX_JOB_AGE_SECONDS = 25 * 3600
DECIDE_TIMEOUT_SECONDS = 5 * 60
HEARTBEAT_TIMEOUT_SECONDS = 120
MAX_FILMS_PER_DAY = 10
MAX_VISITOR_FILMS_PER_DAY = 2
FORM_SLACK_BYTES = 65536


@dataclass
class WebDeps:
    """Everything the app needs from its host."""

    store: object
    authority: object
    runner: object  # callable(spec) -> None; raises only on refused spawn
    jobs_root: object
    examples_root: object
    examples: list = field(default_factory=list)  # [{slug, name}]
    contact: str = "the site operator"
    clock: object = None  # seconds; real time when None
    secure_cookies: bool = False
    ip_secret: str = field(default_factory=lambda: secrets.token_hex(16))


class MemoryStore:
    """Job states for tests and local runs. No locations, no places."""

    def __init__(self, clock=None):
        import time as _time

        self.jobs = {}
        self._mutex = threading.Lock()
        self._clock = clock or _time.time

    def _job(self, job_id):
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError(job_id)

    def create_job(self, job_id, record):
        with self._mutex:
            self.jobs[job_id] = record

    def get_job(self, job_id):
        with self._mutex:
            return dict(self._job(job_id))

    def set_status(self, job_id, status):
        with self._mutex:
            self._job(job_id)["status"] = status

    def append_event(self, job_id, event):
        with self._mutex:
            self._job(job_id)["events"].append(event)

    def set_confirm(self, job_id, confirm):
        with self._mutex:
            job = self._job(job_id)
            job["confirm"] = confirm
            if confirm is not None:
                job["status"] = "confirming"

    def get_decision(self, job_id):
        with self._mutex:
            return self._job(job_id)["decision"]

    def set_decision(self, job_id, confirm):
        with self._mutex:
            self._job(job_id)["decision"] = confirm

    def set_cancel(self, job_id):
        with self._mutex:
            job = self._job(job_id)
            job["cancel"] = True
            if job["status"] in ("started", "confirming", "working"):
                job["status"] = "cancelled"
            if job.get("ended_at") is None:
                job["ended_at"] = self._clock()

    def is_cancelled(self, job_id):
        with self._mutex:
            return self._job(job_id)["cancel"]

    def touch(self, job_id):
        """Mark a poll from the visitor; the worker treats a stale
        heartbeat as a closed tab and cancels."""
        with self._mutex:
            self._job(job_id)["last_poll"] = self._clock()

    def last_poll(self, job_id) -> float:
        with self._mutex:
            job = self._job(job_id)
            return job.get("last_poll") or job.get("started_at", 0.0)

    def end_job(self, job_id, status, result):
        """Close a job with any final status; retention starts now."""
        with self._mutex:
            job = self._job(job_id)
            job["status"] = status
            job["result"] = result
            job["ended_at"] = result.get("ended_at") or self._clock()

    def finish_job(self, job_id, result):
        self.end_job(job_id, "done", result)

    def drop_job(self, job_id):
        with self._mutex:
            self.jobs.pop(job_id, None)

    def job_ids(self):
        with self._mutex:
            return list(self.jobs)


def prune_jobs(store, now, ttl=RETENTION_SECONDS,
               max_age=MAX_JOB_AGE_SECONDS) -> int:
    """Delete jobs (files and records) ended over `ttl` seconds ago.
    Jobs that never ended are deleted past `max_age` after creation,
    so no failure path keeps a photo forever."""
    pruned = 0
    for job_id in store.job_ids():
        try:
            job = store.get_job(job_id)
        except KeyError:
            continue
        ended = job.get("ended_at")
        if ended is not None and now - ended >= ttl:
            pass
        elif now - job.get("started_at", 0) >= max_age:
            pass
        else:
            continue
        shutil.rmtree(job["job_dir"], ignore_errors=True)
        store.drop_job(job_id)
        pruned += 1
    return pruned


def sweep_job_dirs(store, jobs_root, now,
                   max_age=MAX_JOB_AGE_SECONDS) -> int:
    """Delete job folders the store no longer knows (records can
    expire or fail to write): only folders older than `max_age`, so
    an in-flight upload is never touched. Returns the count."""
    known = set()
    for job_id in store.job_ids():
        try:
            known.add(store.get_job(job_id)["job_dir"])
        except KeyError:
            continue
    swept = 0
    root = Path(jobs_root)
    if not root.is_dir():
        return 0
    for entry in sorted(root.iterdir()):
        if (not entry.is_dir() or str(entry) in known
                or entry.stat().st_mtime > now - max_age):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        swept += 1
    return swept


def visitor_key(ip_secret, client_ip, day) -> str:
    """A keyed daily hash of the visitor's network address for the
    cookieless quota. The raw address is never stored; the hash
    rotates every day and dies with the job record."""
    digest = hashlib.sha256()
    digest.update(ip_secret.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(day).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(client_ip).encode("utf-8"))
    return digest.hexdigest()


def admit_upload(deps, vid, vkey, now) -> None:
    """Refuse an upload past the daily film quota or the visitor's
    own quota (cookie and network hash alike), before any file is
    written or job created. Raises SpendingCapExceeded."""
    if deps.authority is not None:
        deps.authority.admit(vid, extra=("ip:" + vkey) if vkey else None)
        return
    cutoff = now - 24 * 3600
    total = mine = keyed = 0
    for job_id in deps.store.job_ids():
        try:
            job = deps.store.get_job(job_id)
        except KeyError:
            continue
        if job.get("started_at", 0) <= cutoff:
            continue
        total += 1
        if job.get("vid") == vid:
            mine += 1
        if vkey and job.get("vkey") == vkey:
            keyed += 1
    if total >= MAX_FILMS_PER_DAY:
        raise models.SpendingCapExceeded("daily quota")
    if mine >= MAX_VISITOR_FILMS_PER_DAY or keyed >= MAX_VISITOR_FILMS_PER_DAY:
        raise models.SpendingCapExceeded("visitor quota")


INDEX_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>The Witness</title>
<style>
.hidden{display:none}
</style>
</head>
<body>
<h1>The Witness</h1>
<h2>Example films</h2>
<ul>
__EXAMPLES__
</ul>
<h2>Try your own photo</h2>
<section id="notice">
<p><strong>Before you upload:</strong> your photo is processed to find and
tell the story of the landmark it shows. It is sent to Meta (recognition,
painting, checks) and Baseten (fact checking). Nearby-place lookups go to
Nominatim, Overpass (including the community mirror), Wikidata and
Wikipedia. Your photo and everything made from it are deleted 24 h after
your film ends. Questions: __CONTACT__.
<a href="/privacy">Full notice</a></p>
</section>
<form id="upload" action="/api/jobs" method="post" enctype="multipart/form-data">
<p><input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required></p>
<p><label><input type="checkbox" name="ack" value="on" required>
I understand the notice above.</label></p>
<p>No location in your photo?
<button type="button" id="geo">Use my location</button>
or type public places only: <input type="text" name="place" autocomplete="off"></p>
<p><input type="hidden" name="lat" id="lat"><input type="hidden" name="lon" id="lon"></p>
<p><button type="submit">Make my film</button></p>
</form>
<div id="job" class="hidden">
<p>Working: <span id="clock">0</span> s</p>
<div id="confirm" class="hidden">
<p>Is this <strong id="confirm-name"></strong> (<span id="confirm-kind"></span>)?</p>
<p><button id="yes">Yes</button> <button id="no">No</button></p>
</div>
<ul id="events"></ul>
<p id="result"></p>
</div>
<script nonce="__NONCE__">
"use strict";
document.getElementById("geo").onclick = () => {
  navigator.geolocation.getCurrentPosition(pos => {
    document.getElementById("lat").value = pos.coords.latitude;
    document.getElementById("lon").value = pos.coords.longitude;
  });
};
const form = document.getElementById("upload");
form.onsubmit = async ev => {
  ev.preventDefault();
  const started = await (await fetch("/api/jobs", {
    method: "POST", body: new FormData(form)})).json();
  if (started.error) { alert(started.error); return; }
  const id = started.job_id;
  document.getElementById("job").style.display = "block";
  document.getElementById("job").dataset.id = id;
  const t0 = Date.now();
  const timer = setInterval(() => {
    document.getElementById("clock").textContent = Math.floor((Date.now() - t0) / 1000);
  }, 500);
  while (true) {
    const st = await (await fetch("/api/jobs/" + id)).json();
    const box = document.getElementById("confirm");
    if (st.confirm && st.decision === null) {
      box.style.display = "block";
      document.getElementById("confirm-name").textContent = st.confirm.name;
      document.getElementById("confirm-kind").textContent = st.confirm.kind;
    } else { box.style.display = "none"; }
    if (["done", "cancelled", "failed", "expired"].includes(st.status)) {
      clearInterval(timer);
      document.getElementById("job").dataset.finished = "yes";
      const r = st.result || {};
      document.getElementById("result").textContent =
        r.film_url ? "Ready." : (r.message || st.status);
      if (r.film_url) {
        const a = document.createElement("a");
        a.href = r.film_url; a.textContent = "Watch your film.";
        document.getElementById("result").appendChild(a);
      }
      break;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
};
document.getElementById("yes").onclick = () => decide(true);
document.getElementById("no").onclick = () => decide(false);
async function decide(confirm) {
  const id = document.getElementById("job").dataset.id;
  await fetch("/api/jobs/" + id + "/decide", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({confirm})});
}
window.addEventListener("pagehide", () => {
  const box = document.getElementById("job");
  const id = box.dataset.id;
  if (id && !box.dataset.finished) {
    navigator.sendBeacon("/api/jobs/" + id + "/cancel");
  }
});
</script>
</body>
</html>
"""

PRIVACY_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Privacy notice: The Witness</title></head>
<body>
<h1>Privacy notice</h1>
<p>The Witness turns your photo of a public landmark into a short film
about that landmark. This page says what is processed, why, by whom
and for how long.</p>
<h2>What you send us</h2>
<p>Your photo (possibly with embedded location), an optional typed
place or browser location when the photo has none, and your confirm
or cancel clicks. Please type public places only.</p>
<h2>Who processes it</h2>
<ul>
<li>Meta: object recognition, era paintings, painting checks.</li>
<li>Baseten (open-weights Muse Spark): fact checking.</li>
<li>Nominatim: typed place to coordinates.</li>
<li>Overpass (including the community mirror): nearby named objects.</li>
<li>Wikidata and Wikipedia: facts and source texts.</li>
</ul>
<h2>How long it is kept</h2>
<p>One rule: your photo and every derivative (clean copy, paintings,
film page) are deleted 24 h after your job ends. No account, no
advertising, no sale. To stop one visitor spending the daily budget,
uploads are counted per visitor: a cookie, plus a keyed hash of the
network address that rotates daily and is kept 24 h. The raw address
is never stored.</p>
<h2>Contact</h2>
<p>Questions or deletion sooner: __CONTACT__.</p>
<p><a href="/">Back</a></p>
</body>
</html>
"""


def _nonce() -> str:
    return secrets.token_urlsafe(16)


def _style_hashes(page: str) -> list:
    """sha256 sources for the page's own <style> blocks, byte for byte
    as the browser hashes them. No inline styles beyond these run."""
    import base64

    hashes = []
    rest = page
    while "<style>" in rest:
        rest = rest.split("<style>", 1)[1]
        block, rest = rest.split("</style>", 1)
        digest = hashlib.sha256(block.encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode("ascii")
                      + "'")
    return hashes


def _csp(nonce: str, style_hashes=()) -> str:
    styles = " ".join(["'self'", *style_hashes])
    return ("default-src 'self'; script-src 'nonce-" + nonce + "'; "
            f"style-src {styles}; img-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; "
            "form-action 'self'")


def create_app(deps: WebDeps) -> FastAPI:
    """Build the page. No global state: every dependency is injected."""
    import time as _time

    clock = deps.clock or _time.time
    store = deps.store
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    def _head(response, request, nonce, correlation):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _csp(
            nonce, getattr(request.state, "style_hashes", ()))
        response.headers["X-Correlation-Id"] = correlation
        return response

    def _refuse(request, detail, status, nonce, correlation):
        return _head(JSONResponse({"error": detail,
                                   "correlation_id": correlation},
                                  status_code=status),
                     request, nonce, correlation)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        nonce = _nonce()
        request.state.nonce = nonce
        correlation = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        request.state.correlation = correlation
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("Origin")
            host = request.headers.get("host", "")
            expected = f"{request.url.scheme}://{host}".lower()
            if origin is None or origin.lower() != expected:
                return _refuse(request, "wrong origin", 403, nonce,
                               correlation)
        if (request.method == "POST" and request.url.path == "/api/jobs"):
            try:
                length = int(request.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > photo_module.MAX_UPLOAD_BYTES + FORM_SLACK_BYTES:
                return _refuse(request, "bad photo: upload too large", 400,
                               nonce, correlation)
        try:
            response = await call_next(request)
        except HTTPException as exc:
            return _refuse(request, exc.detail, exc.status_code, nonce,
                           correlation)
        except Exception:
            return _refuse(request, "something went wrong", 500, nonce,
                           correlation)
        return _head(response, request, nonce, correlation)

    def _vid(request: Request):
        return request.cookies.get("vid")

    def _owned(request: Request, job_id: str):
        try:
            job = store.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such job")
        if not _vid(request) or not secrets.compare_digest(_vid(request), job["vid"]):
            raise HTTPException(status_code=403, detail="not your job")
        try:
            store.touch(job_id)
        except KeyError:
            pass
        return job

    def _deny(request: Request, detail, status):
        return JSONResponse({"error": detail,
                             "correlation_id": request.state.correlation},
                            status_code=status)

    def _browser_fix(lat, lon):
        if not lat and not lon:
            return None, None
        return checked_location((lat, lon))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        items = "".join(
            f'<li><a href="/examples/{ex["slug"]}">{ex["name"]}</a></li>'
            for ex in deps.examples)
        page = INDEX_PAGE.replace("__EXAMPLES__", items)
        page = page.replace("__CONTACT__", deps.contact)
        page = page.replace("__NONCE__", request.state.nonce)
        request.state.style_hashes = _style_hashes(page)
        return HTMLResponse(page)

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy():
        return HTMLResponse(PRIVACY_PAGE.replace("__CONTACT__", deps.contact))

    @app.post("/api/jobs")
    async def start_job(request: Request, photo: UploadFile = File(...),
                        ack: str = Form(None), place: str = Form(""),
                        lat: str = Form(""), lon: str = Form("")):
        if ack != "on":
            return _deny(request, "notice not accepted", 400)
        try:
            fix_lat, fix_lon = _browser_fix(lat, lon)
        except IdentifyError as exc:
            return _deny(request, f"bad location: {exc}", 400)
        vid = _vid(request) or uuid.uuid4().hex
        client_ip = request.client.host if request.client else "unknown"
        day = clock()
        vkey = visitor_key(deps.ip_secret, client_ip,
                           int(day // (24 * 3600)))
        try:
            admit_upload(deps, vid, vkey, day)
        except models.SpendingCapExceeded as exc:
            return _deny(request, f"{exc} spent; try again tomorrow", 429)
        data = b""
        while len(data) <= photo_module.MAX_UPLOAD_BYTES:
            piece = await photo.read(65536)
            if not piece:
                break
            data += piece
        if len(data) > photo_module.MAX_UPLOAD_BYTES or not data:
            return _deny(request, "bad photo", 400)
        job_id = uuid.uuid4().hex
        token = secrets.token_hex(16)
        directory = job_dir(deps.jobs_root)
        tmp = Path(tempfile.mkstemp(dir=directory, suffix=".upload")[1])
        tmp.write_bytes(data)
        try:
            location, today = photo_module.ingest_upload(tmp, directory)
        except photo_module.PhotoError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            return _deny(request, f"bad photo: {exc}", 400)
        started = clock()
        store.create_job(job_id, {
            "vid": vid, "vkey": vkey, "token": token,
            "job_dir": str(directory), "status": "started", "events": [],
            "started_at": started, "last_poll": started, "ended_at": None,
            "confirm": None, "decision": None, "cancel": False,
            "result": None})
        spec = {"job_id": job_id, "token": token, "vid": vid,
                "job_dir": str(directory), "photo": str(today),
                "place": place or "", "lat": fix_lat, "lon": fix_lon,
                "location": ((location.lat, location.lon)
                             if location is not None else None)}
        (directory / "spec.json").write_text(json.dumps(spec))
        try:
            deps.runner({"job_id": job_id, "job_dir": str(directory)})
        except Exception:
            store.end_job(job_id, "failed",
                          {"message": "the worker did not start"})
            raise
        out = JSONResponse({"job_id": job_id})
        out.set_cookie("vid", vid, httponly=True, samesite="lax",
                       secure=deps.secure_cookies)
        return out

    @app.get("/api/jobs/{job_id}")
    async def job_status(request: Request, job_id: str):
        job = _owned(request, job_id)
        return {"status": job["status"], "events": job["events"],
                "started_at": job["started_at"],
                "ended_at": job["ended_at"],
                "elapsed": round(clock() - job["started_at"], 1),
                "confirm": job["confirm"], "decision": job["decision"],
                "result": job["result"]}

    @app.post("/api/jobs/{job_id}/decide")
    async def decide(request: Request, job_id: str):
        _owned(request, job_id)
        body = await request.json()
        store.set_decision(job_id, bool(body.get("confirm")))
        return {"recorded": True}

    @app.delete("/api/jobs/{job_id}")
    async def cancel(request: Request, job_id: str):
        _owned(request, job_id)
        store.set_cancel(job_id)
        return {"cancelled": True}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_post(request: Request, job_id: str):
        """The same cancel over POST: sendBeacon cannot DELETE, so a
        closing tab calls this one."""
        _owned(request, job_id)
        store.set_cancel(job_id)
        return {"cancelled": True}

    def _film_response(request: Request, root: Path, asset: str):
        base = root.resolve()
        target = (base / asset).resolve() if asset else base / "film.html"
        if base not in target.parents and target != base:
            raise HTTPException(status_code=404, detail="no such asset")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no such asset")
        if target.suffix == ".html":
            page = target.read_text().replace(
                "<script>\n", f'<script nonce="{request.state.nonce}">\n', 1)
            request.state.style_hashes = _style_hashes(page)
            return HTMLResponse(page)
        return FileResponse(target)

    @app.get("/film/{job_id}/{token}/{asset:path}")
    async def serve_film(request: Request, job_id: str, token: str, asset: str):
        try:
            job = store.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such film")
        if not secrets.compare_digest(token, job["token"]):
            raise HTTPException(status_code=404, detail="no such film")
        return _film_response(request, Path(job["job_dir"]) / "film", asset)

    @app.get("/examples/{slug}")
    async def serve_example(request: Request, slug: str):
        known = {ex["slug"] for ex in deps.examples}
        if slug not in known:
            raise HTTPException(status_code=404, detail="no such example")
        return _film_response(request, Path(deps.examples_root) / slug, "")

    @app.get("/examples/{slug}/{asset:path}")
    async def serve_example_asset(request: Request, slug: str, asset: str):
        known = {ex["slug"] for ex in deps.examples}
        if slug not in known:
            raise HTTPException(status_code=404, detail="no such example")
        return _film_response(request, Path(deps.examples_root) / slug, asset)

    return app
