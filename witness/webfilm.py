"""One Try-your-own web film, Modal-agnostic and tested."""

import time as _time

from witness import cli, models
from witness.cache import Cache
from witness.webapp import DECIDE_TIMEOUT_SECONDS


def run_web_film(spec, store, authority, clock=None):
    """Identify, confirm, research, paint, render under one job
    ledger and control. `spec` carries the in-memory location and
    place; the store never sees them. Returns a short status."""
    now = clock or _time.time
    job_id = spec["job_id"]
    models.configure_spending(authority=authority)
    control = models.JobControl(deadline_s=spec.get("deadline_s", 1500))
    store.set_status(job_id, "working")
    knowledge = Cache(f"{spec['job_dir']}/knowledge")
    location = tuple(spec["location"]) if spec["location"] else None

    def progress(event, data):
        try:
            store.append_event(job_id, {"t": round(now(), 1),
                                        "event": event, "data": data})
        except KeyError:
            pass

    def decide(found):
        store.set_confirm(job_id, {"name": found.name, "kind": found.kind})
        store.set_decision(job_id, None)
        deadline = _time.monotonic() + DECIDE_TIMEOUT_SECONDS
        while _time.monotonic() < deadline:
            if store.is_cancelled(job_id):
                return False
            answer = store.get_decision(job_id)
            if answer is not None:
                return bool(answer)
            _time.sleep(1.0)
        return False

    def finish(result, status):
        result["ended_at"] = now()
        store.finish_job(job_id, result)
        return {"status": status}

    on_cancel = spec.get("on_cancel")
    if on_cancel is not None:
        on_cancel(control)
    with models.job_ledger(), models.job_control(control=control):
        result = cli.run_job(
            spec["photo"], place=spec["place"] or None, lang="en",
            decide=decide, cache=knowledge, verify_with="baseten",
            progress=progress, quiet=True, location=location,
            out_dir=spec["job_dir"], visitor=spec["vid"],
            control=control, deadline_s=spec.get("deadline_s", 1500))
    store.set_confirm(job_id, None)
    if result.get("cancelled"):
        store.set_cancel(job_id)
        return {"status": "cancelled"}
    if result.get("error_kind") == "quota":
        return finish({"message": result.get("error", "quota spent")},
                      "refused")
    if result.get("capped") or result.get("deadline"):
        return finish({"message": result.get("error", "stopped")}, "stopped")
    if not result.get("identified"):
        return finish(
            {"message": "Not identified. Try a closer photo or a public place."},
            "not_identified")
    if not result.get("confirmed"):
        return finish({"message": "Not confirmed; nothing spent."}, "declined")
    with models.job_ledger(), models.job_control(control=control):
        slug = result["slug"]
        cli.report_and_save(
            result["found"], "en", result["order"], result["kept"],
            result["timeline"], result["chosen"], result["result"],
            result["timings"], "baseten", result["failures"],
            result["comparison"], stream_events=None,
            out_root=spec["job_dir"], quiet=True,
            tokens=result["tokens"], cost_usd=result["cost_usd"])
        outcome = result["result"].get("outcome")
        if outcome in ("full_film", "short_film"):
            progress("painting", {"slug": slug})
            if cli.cmd_paint(slug, spec["photo"], mode="parallel",
                             out_dir=spec["job_dir"]) != 0:
                return finish(
                    {"message": "Research is done but painting failed.",
                     "claims": result["kept"]}, "facts_only")
            progress("render", {"slug": slug})
            if cli.cmd_render(slug, spec["photo"], era_dir="eras_parallel",
                              out_dir=spec["job_dir"], cache=knowledge) != 0:
                return finish(
                    {"message": "Research is done but the film failed.",
                     "claims": result["kept"]}, "facts_only")
            return finish(
                {"film_url": f"/film/{job_id}/{spec['token']}/film.html",
                 "outcome": outcome, "cost_usd": result["cost_usd"]}, "film")
        return finish(
            {"message": "Too little evidence for a film; the facts are below.",
             "claims": result["kept"]}, "facts_only")
