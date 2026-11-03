"""The private web page: upload, progress, capability films.

One FastAPI app serves the pages, the same-origin API and the film
assets. Everything Modal-specific (spawn, Dict, Volume, cron) lives
in modal_app.py; this module takes plain dependencies so the whole
page is testable offline with a fake runner and clock.

Privacy shape: the upload's location and the typed place are
held in the job's private hand-off file (spec.json) only until
the worker reads it, then removed; they never reach the job
store, the film or the logs,
and the research keeps only a coarse season zone. Job films are
served only through unguessable capability URLs. Nothing request-
or location-shaped is ever logged here.
"""

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse)

from witness import models, photo as photo_module
from witness.cli import job_dir
from witness.identify import IdentifyError, checked_location

RETENTION_SECONDS = 24 * 3600
MAX_JOB_AGE_SECONDS = 25 * 3600
DECIDE_TIMEOUT_SECONDS = 5 * 60
HEARTBEAT_TIMEOUT_SECONDS = 120
MAX_FILMS_PER_DAY = 10
MAX_VISITOR_FILMS_PER_DAY = 2
MAX_NETWORK_FILMS_PER_DAY = 2
FORM_SLACK_BYTES = 65536


@dataclass
class WebDeps:
    """Everything the app needs from its host."""

    store: object
    authority: object
    # callable(ref) -> receipt; raises only on refused spawn. A None
    # return means no worker confirmed, so the upload scrubs the
    # location from the spec rather than letting it rest unclaimed.
    runner: object
    jobs_root: object
    examples_root: object
    examples: list = field(default_factory=list)  # [{slug, name}]
    contact: str = "the site operator"
    clock: object = None  # seconds; real time when None
    secure_cookies: bool = False
    ip_secret: str = field(default_factory=lambda: secrets.token_hex(16))
    debug_reset: bool = False  # staging abuse runs only; off everywhere else
    # try_enabled answers the production off switch; None means always on.
    try_enabled: object = None
    noindex: bool = False  # judge mode: unlisted page, never indexed


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


def film_expired(job, now, ttl=RETENTION_SECONDS,
                 max_age=MAX_JOB_AGE_SECONDS) -> bool:
    """True once the job's film and photo read as gone: ended over
    `ttl` seconds ago, or never ended and past `max_age` after
    creation. Mirrors prune_jobs, so reads refuse exactly what the
    sweep would delete."""
    ended = job.get("ended_at")
    if ended is not None:
        return now - ended >= ttl
    return now - job.get("started_at", 0) >= max_age


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
    cookieless quota. The day's key is derived from the shared
    secret first, then the address is hashed under it. The raw
    address is never stored; the hash rotates every day and dies
    with the job record."""
    day_key = hashlib.sha256()
    day_key.update(ip_secret.encode("utf-8"))
    day_key.update(b"\0")
    day_key.update(str(day).encode("utf-8"))
    digest = hashlib.sha256()
    digest.update(day_key.digest())
    digest.update(b"\0")
    digest.update(str(client_ip).encode("utf-8"))
    return digest.hexdigest()


def admit_upload(deps, vid, vkey, now) -> None:
    """Refuse an upload past the daily film quota or the visitor's
    own quota (cookie and network hash alike), before any file is
    written or job created. Raises SpendingCapExceeded. Jobs whose
    worker never started do not count."""
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
        if ((job.get("status") == "failed")
                and (job.get("result") or {}).get("message")
                == "the worker did not start"):
            continue
        total += 1
        if job.get("vid") == vid:
            mine += 1
        if vkey and job.get("vkey") == vkey:
            keyed += 1
    if total >= MAX_FILMS_PER_DAY:
        raise models.SpendingCapExceeded("daily quota")
    if mine >= MAX_VISITOR_FILMS_PER_DAY:
        raise models.SpendingCapExceeded("visitor quota")
    if keyed >= MAX_NETWORK_FILMS_PER_DAY:
        raise models.SpendingCapExceeded("network quota")


def release_upload(deps, vid, vkey) -> None:
    """Refund one admission after a spawn that never started its job.
    Best effort; a failed refund keeps the quota spent."""
    authority = deps.authority
    if authority is None:
        return
    release = getattr(authority, "release", None)
    if release is None:
        return
    try:
        release(vid, extra=("ip:" + vkey) if vkey else None)
    except Exception:
        pass


def _film_limits(deps):
    """The three film limits in force: daily total, per browser and
    per network. From the authority when it names them, else the
    built-in defaults."""
    authority = deps.authority
    if authority is not None:
        daily = getattr(authority, "daily_films", None)
        visitor = getattr(authority, "visitor_films", None)
        network = getattr(authority, "network_films", None)
        if daily is not None and visitor is not None:
            return (daily, visitor,
                    network if network is not None else visitor)
    return (MAX_FILMS_PER_DAY, MAX_VISITOR_FILMS_PER_DAY,
            MAX_NETWORK_FILMS_PER_DAY)


def _quota_refusal(deps, quota: str) -> str:
    """Plain-words refusal naming which limit was reached, when it
    resets and where to watch instead."""
    daily, visitor, network = _film_limits(deps)
    tail = "Resets tomorrow. Meanwhile, the examples below still play."
    if quota == "daily quota":
        return (f"Daily limit reached ({daily} films a day for "
                f"everyone). {tail}")
    if quota == "network quota":
        return (f"Network limit reached ({network} films a day for "
                f"this network). {tail}")
    return (f"Browser limit reached ({visitor} films a day in this "
            f"browser). {tail}")


def _quota_used(deps, vid, vkey, now) -> dict:
    """Films used today overall and by this visitor's own keys."""
    authority = deps.authority
    quota = getattr(authority, "quota", None) if authority else None
    if callable(quota):
        try:
            return quota(vid or "",
                         extra=("ip:" + vkey) if vkey else None)
        except Exception:
            pass
    cutoff = now - 24 * 3600
    used = {"films": 0, "visitor": 0, "network": 0}
    for job_id in deps.store.job_ids():
        try:
            job = deps.store.get_job(job_id)
        except KeyError:
            continue
        if job.get("started_at", 0) <= cutoff:
            continue
        if ((job.get("status") == "failed")
                and (job.get("result") or {}).get("message")
                == "the worker did not start"):
            continue
        used["films"] += 1
        if vid and job.get("vid") == vid:
            used["visitor"] += 1
        if vkey and job.get("vkey") == vkey:
            used["network"] += 1
    return used


def _quota_line(deps, vid, vkey, now) -> str:
    """Plain-words tries before upload: each limit and how many are
    left for this visitor today."""
    daily, visitor, network = _film_limits(deps)
    used = _quota_used(deps, vid, vkey, now)
    daily_left = max(0, daily - used["films"])
    visitor_left = max(0, visitor - used["visitor"])
    network_left = max(0, network - used["network"])
    return (f"{visitor} tries a day in this browser ({visitor_left} "
            f"left today), {network} per network ({network_left} "
            f"left), {daily} total a day ({daily_left} left). "
            "Resets tomorrow.")


INDEX_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="The Witness turns your landmark photo into a short sourced film.">
<title>The Witness</title>
<style>
:root{--paper:#f7f1e3;--card:#fffdf7;--ink:#211b12;--muted:#57503f;--accent:#84301f;--line:#e0d3b8;--serif:"Fraunces",Georgia,"Times New Roman",serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@font-face{font-family:"Fraunces";src:url("/assets/fonts/fraunces-600.woff2") format("woff2");font-weight:600;font-display:swap}
html,body{overflow-x:clip}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.6;margin:0;padding:0 20px 64px}
.wrap{max-width:1020px;margin:0 auto}
h1,h2,h3{font-family:var(--serif);font-weight:600;line-height:1.15;overflow-wrap:break-word;min-width:0}
h1{font-size:clamp(34px,6vw,54px);margin:0 0 12px}
h2{font-size:clamp(24px,4vw,32px);margin:0 0 12px}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
header.top{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:nowrap;padding:20px 0;border-bottom:1px solid var(--line);margin-bottom:36px}
.wordmark{font-family:var(--serif);font-weight:600;font-size:20px;margin:0;white-space:nowrap}
nav.top{display:flex;gap:16px;white-space:nowrap}
nav.top a{margin-left:0;font-size:15px;white-space:nowrap}
.hero{display:grid;gap:20px;margin-bottom:56px}
.hero-left{display:contents}
.hero-title{margin:0 0 12px;order:1}
.hero-body{min-width:0;order:3}
.years{list-style:none;display:flex;margin:0 0 12px;padding:14px 0 0;border-top:2px solid var(--line)}
.years li{position:relative;flex:1;min-width:0;font-size:14px;color:var(--muted)}
.years li::before{content:"";position:absolute;top:-15px;left:2px;width:2px;height:8px;background:var(--accent)}
.years li.playing{color:var(--ink);font-weight:700}
.hero-facts{margin:0;color:var(--muted);font-size:15px}
.lede{font-size:19px;max-width:34em;margin:0 0 20px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 28px}
.btn{display:inline-block;background:var(--ink);color:var(--paper);text-decoration:none;padding:11px 22px;border-radius:999px;font-size:16px}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--ink)}
.hero-media{min-width:0;justify-self:start;order:2}
.hero-video,.hero-still{width:100%;max-width:240px;height:auto;border-radius:10px;background:#000}
.hero-still{display:none}
section.block{margin-bottom:56px}
.steps{display:grid;gap:20px}
.step{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;display:flex;flex-direction:column;min-width:0}
.step-media{height:200px;overflow:hidden;border-radius:8px;margin-bottom:12px}
.step-media img{width:100%;height:100%;object-fit:cover;display:block}
.step h3{margin:0 0 8px;font-size:21px}
.step p{margin:0 0 8px;color:var(--muted)}
.step .fine{font-size:13px}
.fact{margin:12px 0 0;border-top:1px solid var(--line);padding-top:12px}
.fact blockquote{margin:0 0 8px;font-family:var(--serif);font-size:17px;line-height:1.5}
.fact figcaption{font-size:14px;color:var(--muted)}
.promise{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px}
.promise ul{margin:0 0 20px;padding-left:22px}
.promise li{margin-bottom:8px}
.promise figure{margin:0;border-top:1px solid var(--line);padding-top:20px}
.promise blockquote{margin:0 0 8px;font-family:var(--serif);font-size:19px;line-height:1.5}
.promise figcaption{font-size:14px;color:var(--muted)}
.gallery{display:grid;gap:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0}
.card h3{margin:0 0 4px;font-size:21px}
.card .span{margin:0 0 12px;color:var(--muted);font-size:15px}
.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin-bottom:12px}
.pair img{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:6px;display:block}
.card .credit{font-size:13px;color:var(--muted);margin:0 0 12px}
.card .links{display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;font-size:15px}
.pill{border:1px solid var(--accent);border-radius:999px;padding:2px 12px;text-decoration:none;font-size:14px}
.try{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px}
.try .fine{font-size:15px;color:var(--muted)}
#notice ul{margin:0 0 12px;padding-left:22px}
#notice li{margin-bottom:6px}
form p{margin:0 0 12px}
input[type="text"]{font:inherit;max-width:100%}
.file-btn{display:inline-block;background:var(--ink);color:var(--paper);border-radius:999px;padding:10px 22px;cursor:pointer}
.file-btn input{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
#preview{max-width:200px;height:auto;border-radius:8px;margin-top:4px}#preview.hidden{display:none}
#steps{list-style:none;margin:12px 0;padding:0;display:grid;gap:6px}
#steps li{position:relative;padding-left:24px;color:var(--muted)}
#steps li::before{content:"";position:absolute;left:0;top:6px;width:12px;height:12px;border-radius:50%;border:2px solid var(--line);background:transparent}
#steps li.done{color:var(--ink)}
#steps li.done::before{background:var(--accent);border-color:var(--accent)}
#steps li.current{color:var(--ink);font-weight:700}
#steps li.current::before{border-color:var(--accent)}
button{font:inherit;cursor:pointer;background:var(--ink);color:var(--paper);border:none;border-radius:999px;padding:10px 22px}
button#geo,button#yes,button#no{background:transparent;color:var(--ink);border:1px solid var(--ink);padding:6px 16px;font-size:15px}
footer.site{border-top:1px solid var(--line);padding-top:24px;font-size:15px;color:var(--muted)}
.hidden{display:none}
@media (prefers-reduced-motion:reduce){.hero-video{display:none}.hero-still{display:block}}
@media (max-width:520px){header.top{flex-wrap:nowrap;gap:12px}.wordmark{font-size:18px}nav.top{gap:12px}nav.top a{font-size:14px}.only-wide{display:none}}
@media (min-width:760px){.hero{grid-template-columns:minmax(0,1fr) 320px;align-items:center;column-gap:28px}.hero-left{display:flex;flex-direction:column;justify-content:center;min-width:0}.hero-video,.hero-still{max-width:320px}.steps{grid-template-columns:repeat(3,minmax(0,1fr))}.gallery{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
<p class="wordmark">The Witness</p>
<nav class="top" aria-label="Page"><a href="#examples">Examples</a><a href="#try">Try your own</a><a class="only-wide" href="/privacy">Privacy</a></nav>
</header>
<section class="hero" aria-label="Introduction">
<div class="hero-left">
<h1 class="hero-title">Every era it lived through, painted from your photo.</h1>
<div class="hero-body">
<p class="lede">Your landmark, researched and painted back through time, every fact sourced.</p>
<p class="actions"><a class="btn" href="#examples">Watch the examples</a> <a class="btn ghost" href="#try">Try your own photo</a></p>
<ol class="years" aria-label="De Adriaan through time">
<li>1779</li>
<li>1932</li>
<li>2002</li>
<li>today</li>
</ol>
<p class="hero-facts">__HERO_FACTS__</p>
</div>
</div>
<div class="hero-media">
<video class="hero-video" autoplay muted loop playsinline preload="metadata" poster="/assets/landing/hero-poster.jpg" aria-label="Preview of the De Adriaan film: the painted mill in 1779"><source src="/assets/landing/hero.mp4" type="video/mp4"></video>
<img class="hero-still" src="/assets/landing/hero-poster.jpg" width="480" height="854" alt="De Adriaan windmill in Haarlem, painted in 1779 and captioned I was opened">
</div>
</section>
<section class="block" aria-label="How it works">
<h2>How it works</h2>
<div class="steps">
<article class="step">
<div class="step-media"><img src="/assets/landing/step1.jpg" width="1200" height="900" loading="lazy" alt="Today's photo of De Adriaan windmill in Haarlem"></div>
<div><h3>1. Your photo</h3><p>Start with any photo of a landmark, old or new.</p><p class="fine">Today photo: Bj.schoenmakers, CC0, via Wikimedia Commons.</p></div>
</article>
<article class="step">
<div><h3>2. Its sourced history</h3><p>We research what happened here, and check every claim against its sources.</p><figure class="fact"><blockquote>De Adriaan was officially opened on May 19, 1779.</blockquote><figcaption>1779 · <a href="https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem">Wikipedia: De Adriaan, Haarlem</a></figcaption></figure></div>
</article>
<article class="step">
<div class="step-media"><img src="/assets/landing/step3.webp" width="1280" height="1920" loading="lazy" alt="De Adriaan painted in 1932, the year it burnt down"></div>
<div><h3>3. Painted eras</h3><p>Each era is painted from checked evidence. Then the film returns to your photo.</p></div>
</article>
</div>
</section>
<section class="block promise" aria-label="The accuracy promise">
<h2>True, or it is not in the film</h2>
<ul>
<li>Every fact shown links to the page it came from.</li>
<li>Claims without a source are left out of the film.</li>
</ul>
<figure>
<blockquote>Not in the film: in July 2020 the tree was reported as vandalised, with a three-foot section of bark fallen off. No fetched source confirmed it.</blockquote>
<figcaption>From the Major Oak research. The claim was checked and left out.</figcaption>
</figure>
</section>
<section class="block" id="examples" aria-label="Example films">
<h2>Example films</h2>
<p>Three landmarks, researched and painted. Each card opens the film player.</p>
<div class="gallery">
__EXAMPLES__
</div>
</section>
<section class="block try" id="try" aria-label="Try your own photo">
<h2>Try your own photo</h2>
<p>Works best with old, well-documented landmarks: a tower, windmill, lighthouse, old tree or bridge.</p>
<p>__TRY_DURATION__</p>
<p>Sometimes the sources are thin. Then you get the verified facts instead of a film. That is by design.</p>
<p>__QUOTA_LINE__</p>
<p>For adults 18 and over.</p>
__TRY_BLOCK__
<p class="fine">Your photo is deleted after your film. Read the <a href="/privacy">privacy notice</a>.</p>
</section>
<footer class="site">
<p>Built for the Meta Global AI Developer Hackathon with Muse Spark, Muse Image and Muse Spark Open (via Baseten). The example films' subject cutouts were made with SAM 3.1.</p>
<p><a href="https://github.com/debarbanson/the-witness">GitHub</a> · <a href="mailto:__CONTACT__">__CONTACT__</a> · <a href="/privacy">Privacy</a></p>
</footer>
</div>
<script nonce="__NONCE__">
"use strict";
document.getElementById("geo").onclick = () => {
  navigator.geolocation.getCurrentPosition(pos => {
    document.getElementById("lat").value = pos.coords.latitude;
    document.getElementById("lon").value = pos.coords.longitude;
  });
};
const photoInput = document.querySelector('input[name="photo"]');
const preview = document.getElementById("preview");
if (photoInput && preview) {
  photoInput.addEventListener("change", () => {
    const picked = photoInput.files && photoInput.files[0];
    if (picked) {
      preview.src = URL.createObjectURL(picked);
      preview.classList.remove("hidden");
    }
  });
}
const heroVid = document.querySelector(".hero-video");
const yearItems = [...document.querySelectorAll(".years li")];
if (heroVid && yearItems.length) {
  heroVid.addEventListener("timeupdate", () => {
    const idx = heroVid.currentTime < 3 ? 0 : 1;
    yearItems.forEach((li, i) => li.classList.toggle("playing", i === idx));
  });
}
const form = document.getElementById("upload");
const PHASES = {
  identifying: "Finding your object…",
  researched: "Researching its history…",
  verifying: "Checking the facts…",
  captions: "Writing captions…",
  painting: "Painting the eras…",
  children: "Writing the family version…",
  spot: "Making spot-the-difference…",
  render: "Cutting the film…",
  confirmed: "Confirmed.",
  working: "Working…"
};
function phaseWords(name) {
  if (Object.prototype.hasOwnProperty.call(PHASES, name)) { return PHASES[name]; }
  return name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ") + "…";
}
const STEP_FOR = {identifying: 0, identified: 0, confirmed: 0, working: 0, researched: 1, facts: 1, verifying: 2, captions: 3, painting: 3, render: 4, children: 4, spot: 4};
function updateSteps(name) {
  const items = document.querySelectorAll("#steps li");
  if (!items.length) { return; }
  const cur = STEP_FOR[name];
  if (cur === undefined) { return; }
  items.forEach((li, i) => {
    li.classList.toggle("done", i < cur);
    li.classList.toggle("current", i === cur);
  });
}
function showResult(box, st) {
  const r = st.result || {};
  const parts = [r.film_url ? "Ready." : (r.message || st.status)];
  for (const c of r.claims || []) {
    parts.push((c.year ? c.year + ": " : "") + c.claim);
  }
  box.textContent = parts.join(" ");
  if (r.film_url) {
    const a = document.createElement("a");
    a.href = r.film_url; a.textContent = "Watch your film.";
    box.appendChild(document.createTextNode(" "));
    box.appendChild(a);
  }
  for (const c of r.claims || []) {
    if (typeof c.url === "string" && /^https?:\/\//.test(c.url)) {
      const a = document.createElement("a");
      a.href = c.url; a.textContent = " (source)";
      box.appendChild(a);
    }
  }
}
form.onsubmit = async ev => {
  ev.preventDefault();
  let started;
  try {
    started = await (await fetch("/api/jobs", {
      method: "POST", body: new FormData(form)})).json();
  } catch (err) {
    alert("Upload failed. Check your connection and try again.");
    return;
  }
  if (started.error) { alert(started.error); return; }
  const id = started.job_id;
  document.getElementById("job").style.display = "block";
  document.getElementById("job").dataset.id = id;
  const t0 = Date.now();
  const timer = setInterval(() => {
    document.getElementById("clock").textContent = Math.floor((Date.now() - t0) / 1000);
  }, 500);
  let missed = 0;
  while (true) {
    let st;
    try {
      const resp = await fetch("/api/jobs/" + id);
      if (resp.ok === false) { throw new Error("HTTP " + resp.status); }
      st = await resp.json();
    } catch (err) {
      missed += 1;
      if (missed >= 3) {
        clearInterval(timer);
        document.getElementById("job").dataset.finished = "yes";
        document.getElementById("result").textContent =
          "Lost contact with the server (" + err.message + "). Reload to try again.";
        break;
      }
      await new Promise(r => setTimeout(r, 2000));
      continue;
    }
    missed = 0;
    const evs = st.events || [];
    const last = evs.length ? evs[evs.length - 1].event : st.status;
    document.getElementById("events").textContent = phaseWords(last);
    updateSteps(last);
    const box = document.getElementById("confirm");
    if (st.confirm && st.decision === null) {
      box.style.display = "block";
      document.getElementById("confirm-name").textContent = st.confirm.name;
      document.getElementById("confirm-kind").textContent = st.confirm.kind;
    } else { box.style.display = "none"; }
    if (["done", "cancelled", "failed", "expired"].includes(st.status)) {
      clearInterval(timer);
      document.getElementById("job").dataset.finished = "yes";
      showResult(document.getElementById("result"), st);
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

TRY_DURATION_LINE = ("Films usually take about 8 minutes, and the page "
                     "shows each step as it happens.")

TRY_FORM = """<section id="notice">
<p><strong>Before you upload:</strong></p>
<ul>
<li>Your photo is processed to find and tell the story of the landmark it shows.</li>
<li>It is sent to Meta (recognition, painting, checks) and Baseten (fact checking), on hosting by Modal. Nearby-place lookups go to Nominatim, Overpass (including the community mirror), Wikidata and Wikipedia.</li>
<li>Your photo and everything made from it are deleted at the hourly sweep once your film ended over 24 h ago. Questions: __CONTACT__. <a href="/privacy">Full notice</a></li>
</ul>
</section>
<form id="upload" action="/api/jobs" method="post" enctype="multipart/form-data">
<p><label class="file-btn">Take or choose a photo<input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required></label></p>
<p><img id="preview" class="hidden" alt="Preview of your chosen photo"></p>
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
<ol id="steps"><li data-step="identify">Identify</li><li data-step="research">Research</li><li data-step="check">Check</li><li data-step="paint">Paint</li><li data-step="film">Film</li></ol>
<div id="confirm" class="hidden">
<p>Is this <strong id="confirm-name"></strong> (<span id="confirm-kind"></span>)?</p>
<p><button id="yes">Yes</button> <button id="no">No</button></p>
</div>
<ul id="events"></ul>
<p id="result"></p>
</div>"""

TRY_RESTING = ("<p><strong>Try your own is resting; the example "
               "films above still play.</strong> New films are paused "
               "for now.</p>")

LANDING_ASSETS = {"hero.mp4": "video/mp4",
                  "hero-poster.jpg": "image/jpeg",
                  "step1.jpg": "image/jpeg",
                  "step2.jpg": "image/jpeg",
                  "step3.webp": "image/webp"}
FONT_ASSETS = {"fraunces-600.woff2": "font/woff2"}


def _gallery_cards(examples_root, examples) -> str:
    """One card per example film: name, year span, a painted era next
    to today, the player link, and the children's version where it
    exists. Spans and credits come from each film's own film.json;
    a film without one still gets its name and link. An empty
    gallery says so plainly."""
    import html as _html

    cards = []
    for entry in examples:
        slug, name = entry.get("slug", ""), entry.get("name", "")
        if not slug or "/" in slug or slug.startswith("."):
            continue
        base = Path(examples_root) / slug
        film = {}
        try:
            film = json.loads((base / "film.json").read_text())
        except (OSError, ValueError):
            film = {}
        if not isinstance(film, dict):
            film = {}
        years = sorted({scene.get("year")
                        for scene in film.get("segments", [])
                        if isinstance(scene, dict)
                        and isinstance(scene.get("year"), int)})
        span = (f"<p class=\"span\">{years[0]} – {years[-1]}</p>"
                if years else "")
        middle = years[len(years) // 2] if years else None
        era = ""
        if middle is not None and (base / f"era_{middle}.webp").exists():
            era = f"era_{middle}.webp"
        else:
            fallbacks = sorted(base.glob("era_*.webp"))
            era = fallbacks[0].name if fallbacks else ""
        today = "today.jpg" if (base / "today.jpg").exists() else ""
        thumbs = "".join(
            f"<img src=\"/examples/{slug}/{shot}\" loading=\"lazy\" "
            f"alt=\"{_html.escape(name)}: "
            f"{'a painted era' if shot != 'today.jpg' else 'today'}\">"
            for shot in (era, today) if shot)
        pair = (f"<a class=\"pair\" href=\"/examples/{slug}/\" "
                f"aria-label=\"Watch {_html.escape(name)}\">{thumbs}</a>"
                if thumbs else "")
        credit = film.get("photo_credit") or ""
        if not credit:
            source = film.get("photo_source") or {}
            if isinstance(source, dict) and source.get("author"):
                credit = (f"Today photo: {source.get('author')}, "
                          f"{source.get('licence', 'unknown licence')}")
        credit_line = (f"<p class=\"credit\">"
                       f"{_html.escape(credit)}</p>" if credit else "")
        child = (base / "child" / "film.html").exists()
        pill = (f" <a class=\"pill\" "
                f"href=\"/examples/{slug}/child/film.html\">"
                f"Family version</a>" if child else "")
        cards.append(
            f"<article class=\"card\"><h3>{_html.escape(name)}</h3>"
            f"{span}{pair}{credit_line}<p class=\"links\">"
            f"<a href=\"/examples/{slug}/\">Watch the film</a>{pill}</p>"
            f"</article>")
    if not cards:
        return "<p>The example films are on their way.</p>"
    return "\n".join(cards)


def _hero_facts(examples_root, examples) -> str:
    """One line of true numbers under the hero timeline: how many
    reviewed landmarks and painted eras the page shows. Counts come
    from each film's own film.json at request time, so the line is
    true wherever the page runs."""
    shown = [entry for entry in examples if entry.get("slug")]
    eras = 0
    for entry in shown:
        slug = entry.get("slug", "")
        if not slug or "/" in slug or slug.startswith("."):
            continue
        try:
            film = json.loads(
                (Path(examples_root) / slug / "film.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(film, dict):
            continue
        eras += len({scene.get("year")
                     for scene in film.get("segments", [])
                     if isinstance(scene, dict)
                     and isinstance(scene.get("year"), int)})
    if not shown:
        return "Every fact linked to its source."
    landmark = "landmark" if len(shown) == 1 else "landmarks"
    era_word = "painted era" if eras == 1 else "painted eras"
    return (f"{len(shown)} {landmark}, {eras} {era_word}, "
            "every fact linked to its source")


PRIVACY_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Privacy notice: The Witness</title></head>
<body>
<h1>Privacy notice</h1>
<p>The Witness turns your photo of a public landmark into a short film
about that landmark. This page says what is processed, why, by whom
and for how long. For adults 18 and over.</p>
<h2>What you send us</h2>
<p>Your photo (possibly with embedded location), an optional typed
place or browser location when the photo has none, and your confirm
or cancel clicks. Please type public places only.</p>
<h2>Who processes it</h2>
<ul>
<li>Meta: object recognition, era paintings, painting checks.</li>
<li>Baseten (open-weights Muse Spark): fact checking.</li>
<li>Modal: hosts this page and runs the film worker.</li>
<li>Nominatim: typed place to coordinates.</li>
<li>Overpass (including the community mirror): nearby named objects.</li>
<li>Wikidata and Wikipedia: facts and source texts.</li>
</ul>
<h2>How long it is kept</h2>
<p>One rule: your photo and every derivative (clean copy, paintings,
film page) are deleted at the hourly sweep once your job ended over
24 h ago. Your location and typed place are held only until the
worker reads them, then removed from the job file. No account, no
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
            f"style-src {styles}; img-src 'self' blob:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "object-src 'none'; form-action 'self'")


class BodyCapMiddleware:
    """Refuse an over-cap upload body at the ASGI receive level.

    The content-length guard only sees a declared length, and the
    form parser below would otherwise drink a chunked body in full
    before the handler's spool gate runs. So for uploads this
    middleware counts the raw request bytes itself: past the cap it
    answers 400 at once and never reads the rest. Bodies within the
    cap are replayed to the app untouched. The cap is read per
    request so tests can shrink it."""

    def __init__(self, app, noindex=False):
        self.app = app
        self.noindex = noindex

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or scope.get("path") != "/api/jobs"):
            await self.app(scope, receive, send)
            return
        cap = photo_module.MAX_UPLOAD_BYTES + FORM_SLACK_BYTES
        buffered = []
        total = 0
        capped = False
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            total += len(message.get("body", b""))
            if total > cap:
                capped = True
                break
            buffered.append(message)
            if not message.get("more_body"):
                break
        if capped:
            payload = b'{"error":"bad photo: upload too large"}'
            headers = [(b"content-type", b"application/json"),
                       (b"content-length", str(len(payload)).encode()),
                       (b"x-content-type-options", b"nosniff")]
            if self.noindex:
                headers.append((b"x-robots-tag", b"noindex"))
            await send({"type": "http.response.start", "status": 400,
                        "headers": headers})
            await send({"type": "http.response.body", "body": payload})
            return
        buffered_iter = iter(buffered)

        async def replay():
            try:
                return next(buffered_iter)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


def create_app(deps: WebDeps) -> FastAPI:
    """Build the page. No global state: every dependency is injected."""
    import time as _time

    clock = deps.clock or _time.time
    store = deps.store
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(BodyCapMiddleware, noindex=deps.noindex)

    def _head(response, request, nonce, correlation):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _csp(
            nonce, getattr(request.state, "style_hashes", ()))
        response.headers["X-Correlation-Id"] = correlation
        if deps.noindex:
            response.headers["X-Robots-Tag"] = "noindex"
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
        page = INDEX_PAGE.replace(
            "__EXAMPLES__",
            _gallery_cards(deps.examples_root, deps.examples))
        resting = (deps.try_enabled is not None
                   and not deps.try_enabled())
        page = page.replace("__TRY_BLOCK__",
                            TRY_RESTING if resting else TRY_FORM)
        page = page.replace("__TRY_DURATION__", TRY_DURATION_LINE)
        page = page.replace("__HERO_FACTS__",
                            _hero_facts(deps.examples_root, deps.examples))
        import time as _time

        vid = request.cookies.get("vid")
        addr = request.client.host if request.client else None
        now = (deps.clock or _time.time)()
        if addr and deps.ip_secret:
            vkey = visitor_key(deps.ip_secret, addr,
                               int(now // (24 * 3600)))
        else:
            vkey = None
        page = page.replace("__QUOTA_LINE__",
                            _quota_line(deps, vid, vkey, now))
        page = page.replace("__CONTACT__", deps.contact)
        page = page.replace("__NONCE__", request.state.nonce)
        request.state.style_hashes = _style_hashes(page)
        return HTMLResponse(page)

    def _landing_file(folder, catalog, name):
        if name not in catalog:
            raise HTTPException(status_code=404, detail="no such asset")
        target = (Path(__file__).resolve().parent / "landing" / folder
                  / name)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no such asset")
        return FileResponse(target, media_type=catalog[name])

    @app.get("/assets/landing/{name}")
    async def landing_asset(name: str):
        return _landing_file("", LANDING_ASSETS, name)

    @app.get("/assets/fonts/{name}")
    async def font_asset(name: str):
        return _landing_file("fonts", FONT_ASSETS, name)

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy():
        return HTMLResponse(PRIVACY_PAGE.replace("__CONTACT__", deps.contact))

    @app.get("/robots.txt", response_class=PlainTextResponse)
    async def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.post("/api/jobs")
    async def start_job(request: Request, photo: UploadFile = File(...),
                        ack: str = Form(None), place: str = Form(""),
                        lat: str = Form(""), lon: str = Form("")):
        if deps.try_enabled is not None and not deps.try_enabled():
            return _deny(request,
                         "Try your own is resting; the examples are below",
                         503)
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
        data = b""
        while len(data) <= photo_module.MAX_UPLOAD_BYTES:
            piece = await photo.read(65536)
            if not piece:
                break
            data += piece
        if len(data) > photo_module.MAX_UPLOAD_BYTES or not data:
            return _deny(request, "bad photo", 400)
        try:
            photo_module.check_upload_header(data)
        except photo_module.PhotoError as exc:
            return _deny(request, f"bad photo: {exc}", 400)
        job_id = uuid.uuid4().hex
        token = secrets.token_hex(16)
        directory = job_dir(deps.jobs_root)
        upload_fd, upload_path = tempfile.mkstemp(dir=directory,
                                                  suffix=".upload")
        with os.fdopen(upload_fd, "wb") as handle:
            handle.write(data)
        tmp = Path(upload_path)
        try:
            location, today = photo_module.ingest_upload(tmp, directory)
        except photo_module.PhotoError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            return _deny(request, f"bad photo: {exc}", 400)
        try:
            admit_upload(deps, vid, vkey, day)
        except models.SpendingCapExceeded as exc:
            shutil.rmtree(directory, ignore_errors=True)
            return _deny(request, _quota_refusal(deps, str(exc)), 429)
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
        from witness import webfilm as webfilm_module
        try:
            receipt = deps.runner({"job_id": job_id,
                                   "job_dir": str(directory)})
        except Exception:
            try:
                webfilm_module.scrub_hand_off(directory)
            except OSError:
                pass
            release_upload(deps, vid, vkey)
            store.end_job(job_id, "failed",
                          {"message": "the worker did not start"})
            raise
        if receipt is None:
            try:
                webfilm_module.scrub_hand_off(directory)
            except OSError:
                release_upload(deps, vid, vkey)
                store.drop_job(job_id)
                shutil.rmtree(directory, ignore_errors=True)
                return _deny(request, "the worker did not start", 500)
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

    def _debug():
        authority = deps.authority
        if not deps.debug_reset or authority is None:
            raise HTTPException(status_code=404, detail="no such page")
        return authority

    @app.get("/api/debug/ledger")
    async def debug_ledger():
        """Staging abuse runs only: ledger counts, never visitor keys."""
        return _debug().snapshot()

    @app.post("/api/debug/reset-quotas")
    async def debug_reset_quotas():
        """Staging abuse runs only: clear the film and visitor counters
        between cases. Spend totals are kept."""
        _debug().reset_quotas()
        return {"reset": True}

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

    def _film_root(job):
        """The rendered film directory: the stored path first, then
        job_dir/film, then the single nested job_dir/*/film the worker
        renders (one job renders one slug)."""
        base = Path(job["job_dir"]).resolve()
        for candidate in (job.get("film_dir"),
                          (job.get("result") or {}).get("film_dir")):
            if candidate:
                root = Path(candidate).resolve()
                if (base in root.parents or root == base) and root.is_dir():
                    return root
        flat = base / "film"
        if flat.is_dir():
            return flat
        nested = sorted(path.parent for path in base.glob("*/film/film.html")
                        if base in path.resolve().parents)
        if len(nested) == 1:
            return nested[0]
        return flat

    @app.get("/film/{job_id}/{token}/{asset:path}")
    async def serve_film(request: Request, job_id: str, token: str, asset: str):
        try:
            job = store.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such film")
        if not secrets.compare_digest(token, job["token"]):
            raise HTTPException(status_code=404, detail="no such film")
        if film_expired(job, clock()):
            raise HTTPException(status_code=404, detail="no such film")
        return _film_response(request, _film_root(job), asset)

    @app.get("/examples/{slug}")
    async def serve_example(request: Request, slug: str):
        known = {ex["slug"] for ex in deps.examples}
        if slug not in known:
            raise HTTPException(status_code=404, detail="no such example")
        return RedirectResponse(url=f"/examples/{slug}/", status_code=301)

    @app.get("/examples/{slug}/{asset:path}")
    async def serve_example_asset(request: Request, slug: str, asset: str):
        known = {ex["slug"] for ex in deps.examples}
        if slug not in known:
            raise HTTPException(status_code=404, detail="no such example")
        return _film_response(request, Path(deps.examples_root) / slug, asset)

    return app
