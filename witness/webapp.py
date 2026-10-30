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

import secrets
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from witness import photo as photo_module
from witness.cli import job_dir

RETENTION_SECONDS = 24 * 3600
DECIDE_TIMEOUT_SECONDS = 5 * 60


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

    def is_cancelled(self, job_id):
        with self._mutex:
            return self._job(job_id)["cancel"]

    def finish_job(self, job_id, result):
        with self._mutex:
            job = self._job(job_id)
            job["status"] = "done"
            job["result"] = result
            job["ended_at"] = result.get("ended_at") or self._clock()

    def drop_job(self, job_id):
        with self._mutex:
            self.jobs.pop(job_id, None)

    def job_ids(self):
        with self._mutex:
            return list(self.jobs)


def prune_jobs(store, now, ttl=RETENTION_SECONDS) -> int:
    """Delete jobs (files and records) ended over `ttl` seconds ago."""
    pruned = 0
    for job_id in store.job_ids():
        try:
            job = store.get_job(job_id)
        except KeyError:
            continue
        ended = job.get("ended_at")
        if ended is None or now - ended < ttl:
            continue
        shutil.rmtree(job["job_dir"], ignore_errors=True)
        store.drop_job(job_id)
        pruned += 1
    return pruned


INDEX_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>The Witness</title></head>
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
<div id="job" style="display:none">
<p>Working: <span id="clock">0</span> s</p>
<div id="confirm" style="display:none">
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
    if (["done", "cancelled"].includes(st.status)) {
      clearInterval(timer);
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
advertising, no sale.</p>
<h2>Contact</h2>
<p>Questions or deletion sooner: __CONTACT__.</p>
<p><a href="/">Back</a></p>
</body>
</html>
"""


def _nonce() -> str:
    return secrets.token_urlsafe(16)


def _csp(nonce: str) -> str:
    return ("default-src 'self'; script-src 'nonce-" + nonce + "'; "
            "style-src 'unsafe-inline'; img-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; "
            "form-action 'self'")


def create_app(deps: WebDeps) -> FastAPI:
    """Build the page. No global state: every dependency is injected."""
    import time as _time

    clock = deps.clock or _time.time
    store = deps.store
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        nonce = _nonce()
        request.state.nonce = nonce
        correlation = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("Origin")
            if origin and request.url.hostname not in origin:
                return JSONResponse({"error": "wrong origin"}, status_code=403)
        try:
            response = await call_next(request)
        except HTTPException:
            raise
        except Exception:
            return JSONResponse({"error": "something went wrong",
                                 "correlation_id": correlation},
                                status_code=500,
                                headers={"X-Correlation-Id": correlation})
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _csp(nonce)
        response.headers["X-Correlation-Id"] = correlation
        return response

    def _vid(request: Request):
        return request.cookies.get("vid")

    def _owned(request: Request, job_id: str):
        try:
            job = store.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such job")
        if not _vid(request) or not secrets.compare_digest(_vid(request), job["vid"]):
            raise HTTPException(status_code=403, detail="not your job")
        return job

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        items = "".join(
            f'<li><a href="/examples/{ex["slug"]}">{ex["name"]}</a></li>'
            for ex in deps.examples)
        page = INDEX_PAGE.replace("__EXAMPLES__", items)
        page = page.replace("__CONTACT__", deps.contact)
        return HTMLResponse(page.replace("__NONCE__", request.state.nonce))

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy():
        return HTMLResponse(PRIVACY_PAGE.replace("__CONTACT__", deps.contact))

    @app.post("/api/jobs")
    async def start_job(request: Request, photo: UploadFile = File(...),
                        ack: str = Form(None), place: str = Form(""),
                        lat: str = Form(""), lon: str = Form("")):
        if ack != "on":
            raise HTTPException(status_code=400, detail="notice not accepted")
        data = b""
        while len(data) <= photo_module.MAX_UPLOAD_BYTES:
            piece = await photo.read(65536)
            if not piece:
                break
            data += piece
        if len(data) > photo_module.MAX_UPLOAD_BYTES or not data:
            raise HTTPException(status_code=400, detail="bad photo")
        vid = _vid(request) or uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        token = secrets.token_hex(16)
        directory = job_dir(deps.jobs_root)
        tmp = Path(tempfile.mkstemp(dir=directory, suffix=".upload")[1])
        tmp.write_bytes(data)
        try:
            location, today = photo_module.ingest_upload(tmp, directory)
        except photo_module.PhotoError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"bad photo: {exc}")
        store.create_job(job_id, {
            "vid": vid, "token": token, "job_dir": str(directory),
            "status": "started", "events": [], "started_at": clock(),
            "ended_at": None, "confirm": None, "decision": None,
            "cancel": False, "result": None})
        spec = {"job_id": job_id, "token": token, "vid": vid,
                "job_dir": str(directory), "photo": str(today),
                "place": place or "",
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
                "location": ((location.lat, location.lon)
                             if location is not None else None)}
        deps.runner(spec)
        out = JSONResponse({"job_id": job_id})
        out.set_cookie("vid", vid, httponly=True, samesite="lax",
                       secure=deps.secure_cookies)
        return out

    @app.get("/api/jobs/{job_id}")
    async def job_status(request: Request, job_id: str):
        job = _owned(request, job_id)
        return {"status": job["status"], "events": job["events"],
                "started_at": job["started_at"],
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
