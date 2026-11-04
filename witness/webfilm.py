"""One Try-your-own web film, Modal-agnostic and tested."""

import json as _json
import re as _re
import time as _time
import traceback as _traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote as _quote
from urllib.parse import urlparse as _urlparse

from witness import cli, models
from witness.cache import Cache
from witness.photo import PhotoError
from witness.render import builder as render_builder
from witness.verify import filmed, refused
from witness.webapp import DECIDE_TIMEOUT_SECONDS

LANGUAGE_NAMES = {
    "en": "English", "nl": "Dutch", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "da": "Danish", "sv": "Swedish",
    "no": "Norwegian", "pt": "Portuguese", "pl": "Polish", "fy": "Frisian",
}

_QUOTE_LIMIT = 300
_MAX_QUOTES = 3


def read_more_links(qid, articles, lang, website) -> list:
    """Read-more links from Wikidata data only: the run's Wikipedia
    articles (the visitor's language first, then English), the
    official website and the Wikidata page. Https links only; no
    model text can enter, since only these arguments are used."""
    ordered = []
    for code in [lang, "en", *sorted(articles)]:
        if code in articles and code not in ordered:
            ordered.append(code)
    links = []
    for code in ordered:
        if not _re.fullmatch(r"[a-z][a-z0-9-]*", code or ""):
            continue
        title = (articles[code] or "").strip()
        if not title:
            continue
        label = LANGUAGE_NAMES.get(code, code)
        links.append({
            "label": f"Wikipedia ({label})",
            "url": f"https://{code}.wikipedia.org/wiki/"
                   f"{_quote(title.replace(' ', '_'), safe='/:()')}",
        })
    if isinstance(website, str) and website.startswith("https://"):
        links.append({"label": "Official website", "url": website})
    if isinstance(qid, str) and _re.fullmatch(r"Q\d+", qid):
        links.append({"label": "Wikidata",
                      "url": f"https://www.wikidata.org/wiki/{qid}"})
    return links


def _disputed_note(claim) -> bool:
    notes = [str(claim.get("note") or "")]
    notes += [str(entry.get("note") or "")
              for entry in claim.get("support") or []]
    return any("disput" in note.lower() for note in notes)


def source_quotes(kept, texts, checked=()) -> list:
    """Up to 3 source sentences for a no-film result: bound quotes
    that appear literally in a Wikipedia page fetched in this run,
    from claims that are not refused and not disputed, earliest
    year first, skipping facts already listed. Never claim text,
    never official-site wording, at most 300 characters each."""
    seen = set(checked)
    out = []
    ordered = sorted(kept, key=lambda claim: (claim.get("year") is None,
                                              claim.get("year") or 0))
    for claim in ordered:
        url = claim.get("url") or ""
        quote = (claim.get("quote") or "").strip()
        if not quote or quote in seen:
            continue
        if quote == (claim.get("claim") or "").strip():
            continue
        if refused(claim) or _disputed_note(claim):
            continue
        host = _urlparse(url).netloc.lower()
        if not url.startswith("https://") or not host.endswith("wikipedia.org"):
            continue
        if quote not in (texts.get(url) or ""):
            continue
        seen.add(quote)
        if len(quote) > _QUOTE_LIMIT:
            cut = quote[:_QUOTE_LIMIT - 1].rsplit(" ", 1)[0] or quote[:_QUOTE_LIMIT - 1]
            quote = cut + "\u2026"
        out.append({"text": quote, "url": url})
        if len(out) == _MAX_QUOTES:
            break
    return out


display_claim = render_builder.display_claim


def public_claims(kept) -> list:
    """Facts-only payload: filmed claims with their evidence, nothing
    else. Unsupported, partly and refused claims never leave the API."""
    return [{"year": claim.get("year"), "claim": display_claim(claim.get("claim", "")),
             "url": claim.get("url"), "quote": claim.get("quote", "")}
            for claim in kept if filmed(claim)]


def _fetch_outcome(error) -> str:
    """A fetch failure in plain words. The raw error never leaves the
    API: only this fixed vocabulary does."""
    text = str(error or "").lower()
    if "401" in text or "unauthor" in text or "login" in text:
        return "asked for a login"
    if "403" in text or "forbidden" in text or "refus" in text:
        return "refused us"
    if "timeout" in text or "timed out" in text or "total time" in text:
        return "timed out"
    return "couldn't open it"


def source_outcomes(read, failures) -> list:
    """Every checked source with what happened: read, asked for a
    login, refused us, timed out, or couldn't open it. Sorted by
    domain; unconfirmed claim text never appears."""
    from urllib.parse import urlparse

    def domain(url):
        return urlparse(url).netloc.lower().removeprefix("www.")

    seen = {}
    for url in read or []:
        seen[url] = "read"
    for failure in failures or []:
        url = failure.get("url", "")
        seen.setdefault(url, _fetch_outcome(failure.get("error", "")))
    return [{"domain": domain(url), "url": url, "outcome": outcome}
            for url, outcome in sorted(seen.items(),
                                       key=lambda item: (domain(item[0]),
                                                         item[0]))]


def facts_payload(kept, read, failures, stage=None, name=None,
                  links=None, quotes=None) -> dict:
    """The facts-only result: confirmed claims as now, or, with none
    confirmed, real counts plus what happened per source. `stage`
    prefixes its own failure line when the research itself ran,
    `name` is the confirmed landmark in the no-facts line, and
    `links`/`quotes` are the read-more extras (never on a film)."""
    confirmed = public_claims(kept)
    if confirmed:
        payload = {"claims": confirmed}
        if stage:
            payload["message"] = stage
    else:
        sources = source_outcomes(read, failures)
        lead = (f"No film about {name} this time. " if name
                else "No film this time. ")
        message = (f"{lead}We found {len(kept or [])} possible "
                   f"facts in {len(sources)} sources, but couldn't confirm "
                   f"enough of them in sources we could open, so nothing was "
                   f"painted. Well-known landmarks with a Wikipedia page work "
                   f"best.")
        if stage:
            message = f"{stage} {message}"
        payload = {"message": message, "claims": [], "sources": sources}
    if name:
        payload["subject"] = name
    if links:
        payload["links"] = links
    if quotes:
        payload["quotes"] = quotes
    return payload


def no_film_extras(result, knowledge):
    """Read-more links and source quotes for a no-film result, from
    the identified item and the fetched texts only. The website
    lookup is one cached request, skipped quietly on failure."""
    found = result["found"]
    website = cli.identify.official_website(
        getattr(found, "qid", None), cache=knowledge)
    links = read_more_links(
        getattr(found, "qid", None),
        getattr(found, "articles", {}) or {}, "en", website)
    checked = [claim.get("quote", "")
               for claim in public_claims(result["kept"])]
    quotes = source_quotes(result["kept"], result.get("texts") or {},
                           checked)
    return links, quotes


def checked_facts(slug_dir) -> list:
    """The caption-checked scenes in film order: date stamp, sentence
    and source page, exactly as the film shows them. Refused scenes
    never appear; painting may still drop an era, which the painted
    count then reflects."""
    data = _json.loads((Path(slug_dir) / "research.json").read_text(
        encoding="utf-8"))
    claims = data.get("claims", [])
    facts = []
    for scene in data.get("scenes", []):
        if not render_builder.filmable(scene, claims):
            continue
        stamp, text = render_builder.caption_for(scene)
        evidence = (scene.get("caption_sentence") or {}).get("evidence") or {}
        facts.append({"stamp": stamp, "text": text,
                      "url": evidence.get("url", "")})
    return facts


def facts_panel(slug_dir) -> dict:
    """The "Checked so far" panel: the film's facts as items, plus,
    when there are any, the more checked facts the film's end card
    lists. Before painting every caption-checked scene counts as
    filmed; a dropped painting is marked on its item instead."""
    panel = {"items": checked_facts(slug_dir)}
    data = _json.loads((Path(slug_dir) / "research.json").read_text(
        encoding="utf-8"))
    more = render_builder.more_facts(data.get("scenes", []),
                                     data.get("claims", []))
    if more:
        panel["more"] = more
    return panel


def load_spec(job_dir):
    """Read the runner spec the upload route wrote to the job's
    private folder. Spawn arguments carry only the job id; the
    place and location travel in this file, never in logs, and are
    scrubbed from it as soon as the worker reads it."""
    with open(f"{job_dir}/spec.json", encoding="utf-8") as handle:
        return _json.load(handle)


LOCATION_SPEC_KEYS = frozenset({"lat", "lon", "place", "location"})


def scrub_hand_off(job_dir) -> bool:
    """Remove every location key from the job's spec.json, rewritten
    atomically, so the location rests on disk only until the worker
    reads it. Returns True when keys were removed. A missing file
    is a no-op; an unreadable one is deleted and raises, failing
    closed rather than leaving a possibly locating file."""
    import os as _os
    import tempfile as _tempfile

    path = Path(job_dir) / "spec.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    try:
        spec = _json.loads(raw)
    except ValueError:
        path.unlink(missing_ok=True)
        raise ValueError(f"broken job spec in {job_dir}")
    if not isinstance(spec, dict) or not (
            LOCATION_SPEC_KEYS & spec.keys()):
        return False
    for key in LOCATION_SPEC_KEYS:
        spec.pop(key, None)
    handle, tmp = _tempfile.mkstemp(dir=str(path.parent),
                                    prefix="spec.json.",
                                    suffix=".tmp")
    try:
        with _os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(_json.dumps(spec))
        _os.replace(tmp, path)
    except BaseException:
        _os.unlink(tmp) if _os.path.exists(tmp) else None
        raise
    return True


def run_web_film(spec, store, authority, clock=None, nominatim_pace=None,
                 commit=None):
    """Identify, confirm, research, paint, render under one job
    ledger and control. `spec` carries the in-memory location and
    place; the store never sees them. The on-disk hand-off is
    scrubbed first, before any paid call. The film files are
    committed before done and the film URL are published, so a
    poller never sees a film no reader can fetch; a commit failure
    fails the job instead. Returns a short status."""
    scrub_hand_off(spec["job_dir"])
    now = clock or _time.time
    job_id = spec["job_id"]
    models.reset_timing()
    models.configure_spending(authority=authority)
    control = models.JobControl(deadline_s=spec.get("deadline_s", 1500))
    store.set_status(job_id, "working")
    knowledge = Cache(f"{spec['job_dir']}/knowledge")
    location = tuple(spec["location"]) if spec["location"] else None
    if location is None and spec.get("lat") is not None:
        location = (spec["lat"], spec["lon"])

    def progress(event, data):
        try:
            store.append_event(job_id, {"t": round(now(), 1),
                                        "event": event, "data": data})
        except KeyError:
            pass

    def forward_call(row):
        if row.get("op") != "call":
            return
        progress("call", {key: row.get(key) for key in
                          ("op", "phase", "provider", "model",
                           "duration_s")})

    models.on_call_row(forward_call)

    def decide(found):
        store.set_confirm(job_id, {"name": found.name, "kind": found.kind,
                                   "description": getattr(found, "description",
                                                          "") or ""})
        store.set_decision(job_id, None)
        deadline = _time.monotonic() + DECIDE_TIMEOUT_SECONDS
        while _time.monotonic() < deadline:
            if store.is_cancelled(job_id):
                return False
            answer = store.get_decision(job_id)
            if answer is not None:
                if answer:
                    progress("confirmed", {"name": found.name,
                                           "kind": found.kind})
                return bool(answer)
            _time.sleep(1.0)
        return False

    def call_timings():
        rows = models.timing_rows()
        try:
            started = store.get_job(job_id).get("started_at") or 0
        except KeyError:
            started = 0
        base = started or (rows[0]["t"] if rows else 0)
        calls = []
        for row in rows:
            kept = {key: value for key, value in row.items()
                    if key != "t"}
            kept["offset_s"] = round(row["t"] - base, 1)
            calls.append(kept)
        return {"calls": calls}

    def finish(result, status):
        result["ended_at"] = now()
        timings = result.get("timings")
        if not isinstance(timings, dict):
            timings = {}
            result["timings"] = timings
        timings["calls"] = call_timings()["calls"]
        store.finish_job(job_id, result)
        return {"status": status}

    def halted(status, message):
        store.end_job(job_id, status, {"message": message,
                                       "ended_at": now(),
                                       "timings": call_timings()})
        return {"status": status}

    on_cancel = spec.get("on_cancel")
    if on_cancel is not None:
        on_cancel(control)
    try:
        with models.job_ledger(), models.job_control(control=control):
            result = cli.run_job(
                spec["photo"], place=spec["place"] or None, lang="en",
                decide=decide, cache=knowledge, verify_with="baseten",
                progress=progress, quiet=True, location=location,
                out_dir=spec["job_dir"], visitor=spec["vid"],
                control=control, deadline_s=spec.get("deadline_s", 1500),
                pre_admitted=True, nominatim_pace=nominatim_pace,
                reset_timing=False, overpass=False)
    except models.JobCancelled as exc:
        return halted("cancelled", str(exc) or "job cancelled")
    except models.JobDeadlineExceeded as exc:
        return halted("expired", str(exc) or "job deadline passed")
    except Exception:
        _traceback.print_exc()
        return halted("failed", "the runner failed; nothing kept")
    store.set_confirm(job_id, None)
    if result.get("cancelled"):
        return halted("cancelled", result.get("error") or "job cancelled")
    if result.get("error_kind") == "quota":
        return finish({"message": result.get("error", "quota spent")},
                      "refused")
    if result.get("capped") or result.get("deadline"):
        return finish({"message": result.get("error", "stopped")}, "stopped")
    if not result.get("identified"):
        if not spec.get("location") and not (spec.get("place") or "").strip():
            message = ("We couldn't tell which landmark this is. Type its "
                       "name and town under 'Where is it?' and try again.")
        else:
            message = "Not identified. Try a closer photo or a public place."
        return finish({"message": message}, "not_identified")
    if not result.get("confirmed"):
        message = ("Not confirmed. Only the identification ran; "
                   "no research or painting was paid for.")
        return finish({"message": message}, "declined")
    published = False
    try:
        with models.job_ledger() as ledger, models.job_control(control=control):
            slug = result["slug"]

            def total_cost():
                return result["cost_usd"] + ledger.cost_usd

            def facts_only(stage):
                links, quotes = no_film_extras(result, knowledge)
                payload = facts_payload(result["kept"], result.get("read"),
                                        result.get("failures"), stage=stage,
                                        name=result["found"].name,
                                        links=links, quotes=quotes)
                payload["cost_usd"] = total_cost()
                return finish(payload, "facts_only")

            cli.report_and_save(
                result["found"], "en", result["order"], result["kept"],
                result["timeline"], result["chosen"], result["result"],
                result["timings"], "baseten", result["failures"],
                result["comparison"], stream_events=None,
                out_root=spec["job_dir"], quiet=True,
                tokens=result["tokens"], cost_usd=result["cost_usd"])
            outcome = result["result"].get("outcome")
            if outcome in ("full_film", "short_film"):
                progress("captions", {"slug": slug, "model": "Muse Spark"})
                # The anchor photo look overlaps captions; its dated
                # texts are final before captions run. On a captions
                # failure the pool waits for the look, so one vision
                # call may be charged on an already failed job.
                with ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="report") as pool:
                    try:
                        report_future = cli.start_anchor_report(
                            pool, cli.check_respond,
                            cli.photo_bytes_clean(spec["photo"]))
                    except PhotoError:
                        # cmd_paint reports the bad photo, as before.
                        report_future = None
                    if cli.cmd_captions(slug, out_dir=spec["job_dir"],
                                        cache=knowledge) == 2:
                        return facts_only(
                            "Research is done but captions failed.")
                    progress("painting", {"slug": slug, "model": "Muse Image"})
                    try:
                        progress("checked_facts", facts_panel(
                            Path(spec["job_dir"]) / slug))
                    except (OSError, ValueError):
                        pass  # no facts panel; painting still decides

                    def paint_progress(event, data):
                        if event == "painted":
                            progress("painted", data)

                    if cli.cmd_paint(slug, spec["photo"], mode="parallel",
                                     out_dir=spec["job_dir"],
                                     progress=paint_progress,
                                     anchor_future=report_future) != 0:
                        return facts_only(
                            "Research is done but painting failed.")
                progress("render", {"slug": slug})
                if cli.cmd_render(slug, spec["photo"], era_dir="eras_parallel",
                                  out_dir=spec["job_dir"],
                                  cache=knowledge) != 0:
                    return facts_only("Research is done but the film failed.")
                film = {"film_url": f"/film/{job_id}/{spec['token']}/film.html",
                        "film_dir": str(Path(spec["job_dir"]) / slug / "film"),
                        "outcome": outcome, "audiences": "adult",
                        "unavailable": []}
                film["cost_usd"] = total_cost()
                if commit is not None:
                    commit()
                finish(dict(film), "film")
                published = True
                return {"status": "film"}
            links, quotes = no_film_extras(result, knowledge)
            payload = facts_payload(result["kept"], result.get("read"),
                                        result.get("failures"),
                                        name=result["found"].name,
                                        links=links, quotes=quotes)
            payload.setdefault(
                "message",
                "Too little evidence for a film about "
                f"{result['found'].name}; the facts are below.")
            return finish(payload, "facts_only")
    except models.JobCancelled as exc:
        if published:
            return {"status": "film"}
        return halted("cancelled", str(exc) or "job cancelled")
    except models.JobDeadlineExceeded as exc:
        if published:
            return {"status": "film"}
        return halted("expired", str(exc) or "job deadline passed")
    except Exception:
        if published:
            return {"status": "film"}
        _traceback.print_exc()
        return halted("failed", "the runner failed; nothing kept")
