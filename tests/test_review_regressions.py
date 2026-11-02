"""Regression tests from an independent review: each pins the fixed behaviour.

Test names keep the original probe titles (n01 to n33 and the named
ones) so every probe maps to its regression; the asserts state the
safe behaviour. n25 was replaced (the probe only ran ffmpeg itself)
and now tests the real record() command.
"""
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image
from witness import captions, cli, identify, models, paint, photo, verify, web, webapp, webfilm, spot, children
from witness.render import builder


def answer(quote, url="https://example.org/history", verdict="supported"):
    return verify.text_answer(json.dumps({"verdict": verdict, "quote": quote,
        "url": url, "support": [{"url": url, "supports": True, "quote": quote}]}))


def job(**extras):
    return {"claim": "The tower opened in 1900.", "year": 1900,
        "event": "stood", "detail": "The tower stood.", "votes": 1,
        "keywords": ["tower"], "urls": ["https://example.org/history"],
        "passages": ["https://example.org/history\nThe tower opened in 1800 and was repaired much later."],
        **extras}


@pytest.fixture(autouse=True)
def isolate_accounting():
    models.configure_spending()
    models.reset_usage()
    verify.clear_cache()
    identify.clear_cache()
    yield
    models.configure_spending()
    models.reset_usage()
    verify.clear_cache()
    identify.clear_cache()

URL = "https://example.org/history"
QUOTE = "The tower was built in 1900 with a stone roof."


def evidence_claim(**changes):
    return {"year": 1900, "claim": "The tower was built in 1900.", "event": "built", "completed": True,
            "verdict": "supported", "quote": QUOTE, "url": URL, "sources": [URL], "war_politics_only": False,
            **changes}


def evidence_scene(**changes):
    return {"from_year": 1900, "date_label": "1900", "state": {"condition": "standing", "description": "stone roof"},
        "caption_lines": [], "caption_sentence": {"text": "I rose with a stone roof.", "claim_year": 1900, "claim_url": URL,
        "evidence": {"claim": "The tower was built in 1900.", "quote": QUOTE, "url": URL}}, **changes}


def make_client(tmp_path, runner=None, store=None, examples=None):
    from fastapi.testclient import TestClient
    store = store or webapp.MemoryStore()
    deps = webapp.WebDeps(store=store, authority=None, runner=runner or (lambda spec: None),
        jobs_root=tmp_path / "jobs", examples_root=tmp_path / "examples", examples=examples or [])
    return TestClient(webapp.create_app(deps), raise_server_exceptions=False), store


def new_record(directory, **extras):
    return {"vid": "synthetic-owner", "token": "synthetic-capability", "job_dir": str(directory),
        "status": "working", "events": [], "started_at": 0, "ended_at": None, "confirm": None,
        "decision": None, "cancel": False, "result": None, **extras}


def new_spec(tmp_path):
    return {"job_id": "synthetic-job", "token": "synthetic-capability", "vid": "synthetic-owner",
        "job_dir": str(tmp_path), "photo": "synthetic-photo", "place": "", "location": None,
        "lat": None, "lon": None}


def success_result(**extras):
    return {"identified": True, "confirmed": True, "cached": False, "slug": "synthetic-tower",
        "found": SimpleNamespace(name="Synthetic Tower", kind="tower", qid="Q1", articles={}),
        "order": [], "kept": [], "timeline": [], "chosen": [], "result": {"outcome": "full_film"},
        "timings": {}, "failures": [], "comparison": None, "tokens": {}, "cost_usd": 0.0, **extras}


def test_four_calls_pass_without_reserving_budget(tmp_path):
    """Over-cap calls are all refused and the provider sees nothing."""
    calls = []
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(1) or {"usage": {}}))
    models.configure_spending(tmp_path, daily_cap_usd=0.005)
    def attempt(_):
        with pytest.raises(models.SpendingCapExceeded):
            models.respond(client, models.PAINT)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(attempt, range(4)))
    assert calls == []


def test_unfetched_quote_is_accepted():
    """A quote from no fetched passage is not supported."""
    forged = "The tower opened in 1900 with a spectacular golden roof."
    result = verify.judge_claim(lambda _: answer(forged), job(), completion=False)
    assert result["verdict"] == "unsupported"
    assert not verify.is_literal_quote(forged, job()["passages"], 1900, ["tower"])


def test_literal_quote_is_not_bound_to_its_claimed_url():
    """The accepted URL is the fetched passage holding the quote."""
    quote = "The tower opened in 1900 with a spectacular golden roof."
    result = verify.judge_claim(lambda _: answer(quote, "https://unfetched.invalid/"),
        job(passages=["https://example.org/history\n" + quote]), completion=False)
    assert result["verdict"] == "supported"
    assert result["url"] == "https://example.org/history"


def test_anchor_accepts_negation_and_skips_dispute_check():
    """A negated anchor sentence confirms nothing, so no dispute is needed."""
    checked = []
    result = verify.judge_claim(lambda _: answer("", verdict="unsupported"),
        job(anchor="build", passages=["https://example.org/history\nThe tower was not built in 1900, despite popular claims."]),
        dispute_check=lambda *args: checked.append(True) or False)
    assert checked == []
    assert result["verdict"] == "unsupported"


def test_completion_failure_preserves_completed_true():
    """A failed completion check leaves the claim uncompleted."""
    def fail(_):
        raise TimeoutError("synthetic transport failure")
    quote = "In 1900 the town proposed that the tower should be rebuilt."
    result = verify.judge_claim(lambda _: answer(quote),
        job(event="rebuilt", detail="The tower was rebuilt.", passages=["https://example.org/history\n" + quote]),
        completion_respond=fail)
    assert result["verdict"] == "supported"
    assert result["completed"] is False
    assert "failed" in result["completion_note"]


def test_partly_supported_caption_keeps_unsupported_detail():
    """A partly verdict never verifies a caption sentence."""
    result = captions.write_sentence(lambda *a: "I grew a golden roof and flew away.",
        lambda *a: "partly", {"claim": "The roof changed.", "quote": "The roof changed."}, 1900)
    assert result["verified"] is False
    assert result["sentence"] is None


def test_jpeg_comment_survives_cleaning(tmp_path):
    """Cleaning strips the JPEG comment from both copies."""
    src = tmp_path / "upload.jpg"
    marker = b"synthetic private metadata marker"
    Image.new("RGB", (8, 8)).save(src, comment=marker)
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert Image.open(dest).info.get("comment") is None
    assert Image.open(io.BytesIO(photo.photo_bytes_clean(src))).info.get("comment") is None


def test_ingest_error_leaves_original_on_disk(tmp_path, monkeypatch):
    """The original upload is deleted even when cleaning fails."""
    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src)
    def fail(*args):
        raise OSError("synthetic encoder failure")
    monkeypatch.setattr(photo, "prepare_photo", fail)
    with pytest.raises(OSError):
        photo.ingest_upload(src, tmp_path / "job")
    assert not src.exists()


def test_typed_place_is_echoed_in_error():
    """Geocode failures name no typed place."""
    marker = "SYNTHETIC_PRIVATE_PLACE"
    identify.clear_cache()
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
    with pytest.raises(identify.NotIdentifiedError) as exc:
        identify.geocode(marker, get=lambda *a, **k: response, sleep=lambda _: None)
    assert marker not in str(exc.value)


def test_redirect_is_checked_only_after_fetch(monkeypatch):
    """A private redirect is refused before any second request."""
    seen = []
    monkeypatch.setattr(web, "resolve_public_ips", lambda host: ["93.184.216.34"])
    def sender(url, **kwargs):
        seen.append(url)
        return SimpleNamespace(status_code=302, headers={"Location": "http://127.0.0.1/private"}, close=lambda: None)
    with pytest.raises(web.WebError):
        web.fetch_public("https://example.org/public", sender=sender)
    assert seen == ["https://example.org/public"]


def test_mixed_public_private_dns_is_allowed(monkeypatch):
    """A host resolving to any private address is refused."""
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *a: [
        (2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(web.WebError):
        web.assert_public_url("https://example.org/")


def test_nat64_loopback_url_is_allowed():
    """A NAT64 loopback address is refused."""
    with pytest.raises(web.WebError):
        web.assert_public_url("http://[64:ff9b::7f00:1]/")


def test_capped_job_result_crashes_film_command(monkeypatch):
    """A capped job exits cleanly with code 2."""
    monkeypatch.setattr(cli, "run_job", lambda *a, **k: {
        "identified": True, "confirmed": True, "cached": False, "capped": True})
    assert cli.cmd_film("unused", yes=True) == 2


def test_reviewed_cache_skips_decline(tmp_path, monkeypatch):
    """A cached hit still asks, and a decline stops the job."""
    found = SimpleNamespace(name="Synthetic Tower", kind="tower", qid="Q1",
        articles={}, country_code="gb")
    monkeypatch.setattr(identify, "identify", lambda *a, **k: found)
    decisions = []
    cache = SimpleNamespace(get_reviewed=lambda *a: {"outcome": {"outcome": "short_film"}})
    result = cli.run_job("unused", cache=cache, quiet=True, out_dir=tmp_path,
        decide=lambda _: decisions.append(False) or False)
    assert decisions == [False]
    assert result["confirmed"] is False


def test_aftermath_retry_drops_photo_after_safety_error():
    """The aftermath retry re-sends the photo after a safety refusal."""
    seen = []
    def call(prompt, prev, image):
        seen.append(image is not None)
        if len(seen) == 1:
            raise paint.PaintSafetyError("synthetic refusal")
        return {"image": b"fake", "response_id": "synthetic"}
    result = paint.paint_aftermath(call, lambda *a: "MATCHES", {
        "from_year": 1900, "state": {"condition": "burnt"}}, "Tower", "Town",
        photo_bytes=b"synthetic image")
    assert result["verdict"] == "matches"
    assert seen == [True, True]


def test_rerender_leaves_previous_cutout_file(tmp_path):
    """A re-render without a cut-out drops the stale cutout.png."""
    cutout = tmp_path / "synthetic.png"
    Image.new("RGBA", (8, 8)).save(cutout)
    research = {"object": {"name": "Tower"}, "claims": [evidence_claim()],
                "scenes": [evidence_scene()]}
    images = {"1900": "e/1900.png"}
    first = builder.write_film(tmp_path / "job", research, images, "today.jpg", "", cutout_file=cutout)
    assert (first / "cutout.png").exists()
    film = builder.write_film(tmp_path / "job", research, images, "today.jpg", "", cutout_file=None)
    assert json.loads((film / "film.json").read_text())["cutout"] is None
    assert not (film / "cutout.png").exists()


def test_filmable_does_not_require_verified_claim_or_source():
    """A sentence without evidence never reaches the film."""
    assert not builder.filmable({"caption_sentence": {"text": "I flew away.", "claim_year": 1900}}, [])


def test_war_flag_is_not_removed_from_timeline():
    """A war-only claim is refused everywhere, timeline included."""
    claim = {"year": 1900, "claim": "The tower was bombed in war.",
        "event": "destroyed", "verdict": "supported", "war_politics_only": True,
        "quote_span": "The tower was bombed in war.", "rewritten": None}
    verified, timeline, chosen = cli.refresh_film([claim])
    assert verified == []
    assert all(seg.get("from_year") != 1900 for seg in timeline)
    assert all(scene.get("from_year") != 1900 for scene in chosen)


def test_visible_change_bypasses_claim_verification():
    """An unverified visible change never reaches the state or prompt."""
    invented = "A golden roof and six purple spires."
    claim = {"year": 1900, "claim": "The tower was built in 1900.",
        "event": "built", "quote_span": "The tower was built.",
        "visible_change": invented, "sources": ["https://example.org/history"],
        "verdict": "supported", "war_politics_only": False, "rewritten": None}
    verification_job = cli.build_jobs([claim], {}, [], 1900)[0]
    assert invented not in verification_job["claim"]
    assert invented not in verification_job["detail"]
    _, timeline, chosen = cli.refresh_film([claim])
    assert timeline[0]["state"]["description"] == "The tower was built."
    assert invented not in paint.scene_prompt(chosen[0], "Tower", "Town")


def test_film_save_uses_restored_outer_ledger(monkeypatch):
    """The saved cost is the job's real spend, never zeroed."""
    models.reset_usage()
    @models.with_job_ledger
    def fake_run(*args, **kwargs):
        models.current_ledger().note("meta", "muse-spark-1.3", {"input_tokens": 1000})
        return {"identified": True, "confirmed": True, "cached": False,
            "chosen": [], "order": [], "kept": [], "timeline": [], "result": {},
            "timings": {"total_s": 1}, "failures": [],
            "tokens": models.usage_totals(), "cost_usd": models.current_cost_usd()}
    saved = []
    def save(*args, **kwargs):
        saved.append(kwargs.get("cost_usd", models.current_cost_usd()))
    monkeypatch.setattr(cli, "run_job", fake_run)
    monkeypatch.setattr(cli, "report_and_save", save)
    for name in ("cmd_captions", "cmd_paint", "cmd_render"):
        monkeypatch.setattr(cli, name, lambda *a, **k: 0)
    assert cli.cmd_film("unused", yes=True) == 0
    assert saved == [pytest.approx(0.00125)]


def test_n01_ambiguous_failure_releases_all_budget(tmp_path):
    """A failed call keeps its ceiling counted as spent."""
    models.configure_spending(tmp_path, daily_cap_usd=0.10)
    def create(**kwargs):
        raise TimeoutError("synthetic response lost after provider work")
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with pytest.raises(TimeoutError):
        models.respond(client, models.VERIFY)
    assert models._DAILY.total_usd() == pytest.approx(0.10)
    assert models._DAILY.reserved_usd() == 0.0


def test_n02_actual_cost_exceeds_reserved_ceiling(tmp_path):
    """An oversized input is refused before it reserves anything."""
    models.configure_spending(tmp_path, daily_cap_usd=0.10)
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: {"usage": {"input_tokens": 100000, "output_tokens": 2048}}))
    with pytest.raises(models.SpendingCapExceeded):
        models.respond(client, models.VERIFY, input="A " * 100000)
    assert models._DAILY.total_usd() == 0.0


def test_n03_budget_ticket_can_reconcile_twice(tmp_path):
    """A ticket reconciles once; the second reconcile is refused."""
    authority = models.BudgetAuthority(tmp_path, daily_cap_usd=0.20)
    first = authority.reserve(0.10)
    authority.reserve(0.10)
    authority.reconcile(first, 0.01)
    with pytest.raises(models.AccountingError):
        authority.reconcile(first, 0.01)
    assert authority.reserved_usd() == pytest.approx(0.10)
    assert authority.total_usd() == pytest.approx(0.01)


def test_n04_empty_account_resets_to_zero(tmp_path):
    """An existing but empty account fails closed."""
    authority = models.BudgetAuthority(tmp_path, daily_cap_usd=0.10)
    authority._file().write_text("")
    with pytest.raises(models.AccountingError):
        authority.reserve(0.10)


def test_n05_nonwiki_tuple_timeout_breaks_pinned_socket(monkeypatch):
    """A timeout tuple is normalised; the socket gets a scalar."""
    monkeypatch.setattr(web, "resolve_public_ips", lambda host: ["93.184.216.34"])
    seen = []
    def connect(address, timeout):
        seen.append(timeout)
        raise OSError("synthetic stop after the timeout check")
    monkeypatch.setattr(web.socket, "create_connection", connect)
    with pytest.raises(OSError, match="synthetic stop"):
        web._pinned_send("https://example.org/", timeout=(1, 2))
    assert seen == [1]


def test_n06_total_deadline_not_checked_while_reading(monkeypatch):
    """A body arriving past the total deadline is refused."""
    clock = [0.0]
    monkeypatch.setattr(web.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(web, "assert_public_url", lambda _: None)
    class Resp:
        status_code = 200
        headers = {}
        def iter_content(self, n):
            clock[0] = 999.0
            yield b"late body"
        def close(self):
            pass
    with pytest.raises(web.WebError, match="total time"):
        web.fetch_public(URL, sender=lambda *a, **k: Resp(), total_timeout=1)


def test_n07_anchor_wrong_object_is_supported():
    """An other-object sentence never confirms the build anchor."""
    quote = "The nearby warehouse was built in 1900 beside the old tower."
    result = verify.judge_claim(lambda _: answer("", verdict="unsupported"),
        job(anchor="build", passages=[URL + "\n" + quote]))
    assert result["verdict"] == "unsupported"
    assert result.get("fast_path") is None


def test_n08_generic_completion_quote_is_accepted():
    """A short unbound completion quote does not complete the claim."""
    quote = "In 1900 the tower was proposed for reconstruction but never built."
    result = verify.judge_claim(lambda _: answer(quote), job(event="rebuilt", detail="rebuilt", passages=[URL + "\n" + quote]),
        completion_respond=lambda _: verify.text_answer(json.dumps({"completed": True, "quote": "the"})))
    assert result["completed"] is False


def test_n09_evidence_attaches_to_wrong_scene_year():
    """A caption citing another year's claim is not filmable."""
    scene = evidence_scene(from_year=2000, date_label="2000")
    assert not builder.filmable(scene, [evidence_claim()])


def test_n10_changed_claim_with_same_quote_keeps_caption():
    """A caption whose claim changed is not filmable."""
    assert not builder.filmable(evidence_scene(), [evidence_claim(claim="A different event from the same paragraph.")])


def test_n11_empty_eras_still_successful_film_plan():
    """No filmable era means an empty plan, never a film."""
    plan = builder.build_timeline([evidence_scene()], {}, [evidence_claim()])
    assert plan == []


def test_n12_reloaded_unverified_visuals_reach_both_painters(tmp_path, monkeypatch):
    """Reloaded descriptions the quote does not state are blanked first."""
    scene = evidence_scene(state={"condition": "standing", "description": "UNVERIFIED purple spires"})
    scene["caption_sentence"]["child"] = {"text": "I rose with a stone roof."}
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "research.json").write_text(json.dumps({"object": {"name": "Tower", "country_code": "gb"}, "claims": [evidence_claim()], "scenes": [scene]}))
    monkeypatch.setattr(cli, "photo_bytes_clean", lambda _: b"synthetic")
    monkeypatch.setattr(identify, "capture_month", lambda _: None)
    monkeypatch.setattr(paint, "paint_directives", lambda *a: {"season": "summer", "excluded": {}})
    seen = []
    def parallel(*args, **kwargs):
        seen.append((args[2][0]["state"]["description"], kwargs["audience"]))
        return [{"image": None, "verdict": "dropped", "attempts": 1, "note": "synthetic"}]
    monkeypatch.setattr(paint, "paint_parallel", parallel)
    monkeypatch.setattr(cli, "recover_or_retry", lambda *a, **k: a[8])
    deny = lambda _: answer("", verdict="unsupported")
    for audience in ("adult", "child"):
        assert cli.cmd_paint("synthetic", "unused", out_dir=tmp_path, audience=audience, photo_month=1, support_call=deny) == 0
    assert seen == [("", "adult"), ("", "child")]


def test_n13_caption_bundle_drops_actual_check_evidence(tmp_path, monkeypatch):
    """The saved evidence is the sentence the caption was checked on."""
    root = tmp_path / "synthetic"
    root.mkdir()
    claim = evidence_claim()
    scene = evidence_scene()
    scene.pop("caption_sentence")
    (root / "research.json").write_text(json.dumps({"object": {"name": "Tower"}, "claims": [claim], "scenes": [scene]}))
    extra = "In 1900 the tower gained a blue roof after the stone roof collapsed."
    monkeypatch.setattr(cli, "caption_texts", lambda *a: {URL: extra})
    monkeypatch.setattr(cli, "recheck_paintings", lambda *a: [])
    def support(sentence, passages, year, keywords):
        if any(extra in p for p in passages):
            return {"verdict": "supported", "quote": extra, "url": URL}
        return {"verdict": "unsupported", "quote": "", "url": None}
    assert cli.cmd_captions("synthetic", out_dir=tmp_path, cache=object(), rewrite_call=lambda *a: "I gained a blue roof.", support_call=support) == 0
    saved = json.loads((root / "research.json").read_text())["scenes"][0]["caption_sentence"]
    assert "blue roof" in saved["text"]
    assert extra in saved["evidence"]["quote"]


def test_n14_spot_accepts_arbitrary_text_with_reused_grounding():
    """Repeated grounding lines collapse to one, so no game is offered."""
    changes = ["1900: roof lost", "1950: rebuilt", "2000: moved"]
    result = spot.choose(lambda *a: [{"text": f"Invented difference {i}", "change": changes[0]} for i in range(3)], b"x", b"y", changes)
    assert result is None


def test_n15_main_film_route_looks_in_wrong_directory(tmp_path):
    """The film route serves the job's nested film directory."""
    import time as _time

    client, store = make_client(tmp_path)
    directory = tmp_path / "private-job"
    film = directory / "synthetic-tower" / "film"
    film.mkdir(parents=True)
    (film / "film.html").write_text("synthetic film")
    store.create_job("id", new_record(directory,
                                      started_at=_time.time()))
    served = client.get("/film/id/synthetic-capability/film.html")
    assert served.status_code == 200
    assert "synthetic film" in served.text


def test_n16_example_without_slash_breaks_relative_assets(tmp_path):
    """Example pages redirect so relative assets resolve."""
    from urllib.parse import urljoin
    client, store = make_client(tmp_path, examples=[{"slug": "demo", "name": "Demo"}])
    directory = tmp_path / "examples" / "demo"
    directory.mkdir(parents=True)
    (directory / "film.html").write_text('<img src="today.jpg">')
    (directory / "today.jpg").write_bytes(b"synthetic fixture; not an image")
    page = client.get("/examples/demo")
    assert page.status_code == 200
    assert client.get(urljoin(str(page.url), "today.jpg")).status_code == 200


def test_n17_error_and_origin_rejection_miss_security_headers(tmp_path):
    """Refusals and crashes carry the security headers too."""
    def broken(spec):
        raise RuntimeError("synthetic")
    client, _ = make_client(tmp_path, runner=broken)
    bad = client.post("/api/jobs", headers={"Origin": "https://foreign.invalid"})
    assert bad.status_code == 403
    assert "content-security-policy" in bad.headers
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    failed = client.post("/api/jobs", files={"photo": ("x.png", buf.getvalue())}, data={"ack": "on"},
                         headers={"Origin": "http://testserver"})
    assert failed.status_code == 500
    assert "content-security-policy" in failed.headers


def test_n18_origin_substring_bypass(tmp_path):
    """A foreign origin merely containing the host is refused."""
    client, _ = make_client(tmp_path)
    response = client.post("/api/jobs", headers={"Origin": "https://testserver.attacker.invalid"})
    assert response.status_code == 403


def test_n19_cancelled_and_crashed_jobs_never_expire(tmp_path):
    """A cancelled job is pruned with its files."""
    directory = tmp_path / "job"
    directory.mkdir()
    (directory / "derivative.txt").write_text("synthetic")
    store = webapp.MemoryStore()
    store.create_job("id", new_record(directory))
    store.set_cancel("id")
    assert webapp.prune_jobs(store, 10 * webapp.RETENTION_SECONDS) == 1
    assert not directory.exists()


def test_n20_browser_location_is_not_forwarded_to_identify(tmp_path, monkeypatch):
    """The browser fix reaches the job; the store never sees it."""
    spec = new_spec(tmp_path)
    spec.update(lat=1.25, lon=2.25)
    store = webapp.MemoryStore()
    store.create_job(spec["job_id"], new_record(tmp_path))
    seen = []
    def run(*a, **kw):
        seen.append(kw["location"])
        return {"identified": False}
    monkeypatch.setattr(cli, "run_job", run)
    webfilm.run_web_film(spec, store, SimpleNamespace())
    assert seen == [(1.25, 2.25)]


def test_n21_render_phase_cancel_escapes_and_leaves_working_job(tmp_path, monkeypatch):
    """A render-phase cancel closes the job as cancelled."""
    spec = new_spec(tmp_path)
    store = webapp.MemoryStore()
    store.create_job(spec["job_id"], new_record(tmp_path))
    monkeypatch.setattr(cli, "run_job", lambda *a, **k: success_result())
    monkeypatch.setattr(cli, "report_and_save", lambda *a, **k: None)
    def stop(*a, **kw):
        raise models.JobCancelled("synthetic")
    monkeypatch.setattr(cli, "cmd_captions", stop)
    assert webfilm.run_web_film(spec, store, SimpleNamespace()) == {"status": "cancelled"}
    finished = store.get_job(spec["job_id"])
    assert finished["status"] == "cancelled"
    assert finished["ended_at"] is not None


def test_n22_headers_allow_inline_styles(tmp_path):
    """The CSP carries no unsafe-inline style source."""
    client, _ = make_client(tmp_path)
    assert "unsafe-inline" not in client.get("/").headers["content-security-policy"]


def test_n23_original_upload_file_descriptor_is_not_closed(tmp_path, monkeypatch):
    """The spool file descriptor is closed after the upload lands."""
    client, _ = make_client(tmp_path)
    seen = []
    original = webapp.tempfile.mkstemp
    def mkstemp(*a, **k):
        fd, path = original(*a, **k)
        seen.append(fd)
        return fd, path
    monkeypatch.setattr(webapp.tempfile, "mkstemp", mkstemp)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    posted = client.post("/api/jobs", files={"photo": ("x.png", buf.getvalue())}, data={"ack": "on"},
                         headers={"Origin": "http://testserver"})
    assert posted.status_code == 200
    assert seen
    try:
        for fd in seen:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        for fd in seen:
            try:
                os.close(fd)
            except OSError:
                pass


def test_n24_pixel_limit_checked_after_decode(tmp_path, monkeypatch):
    """The pixel cap refuses from the header, before any decode."""
    seen = []
    class FakeImage:
        size = (100000, 100000)
        format = "PNG"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def load(self):
            seen.append("decoded")
        def convert(self, *a):
            return self
    path = tmp_path / "synthetic.dat"
    path.write_bytes(b"fake")
    monkeypatch.setattr(photo.Image, "open", lambda *a: FakeImage())
    monkeypatch.setattr(photo.ImageOps, "exif_transpose", lambda x: x)
    with pytest.raises(photo.PhotoError):
        photo.load_clean(path)
    assert seen == []


def test_n25_record_forces_mp4_muxer(tmp_path, monkeypatch):
    """The real record() names -f mp4 before the partial path."""
    from witness.render import record as record_module
    film_dir = tmp_path / "film"
    film_dir.mkdir()
    (film_dir / "film.html").write_text("<html></html>")
    (film_dir / "film.json").write_text(json.dumps({"segments": [{"end": 0.1}]}))
    seen = []
    class FakeProc:
        def __init__(self, argv, **kwargs):
            seen.append(argv)
            Path(argv[-1]).write_bytes(b"fake mp4 bytes")
            self.stdin = io.BytesIO()
            self.returncode = 0
        def communicate(self):
            return (None, b"")
    monkeypatch.setattr(record_module.subprocess, "Popen", FakeProc)
    class FakePage:
        def goto(self, url):
            pass
        def wait_for_function(self, js):
            pass
        def evaluate(self, js):
            pass
        def screenshot(self):
            return b"fake-frame"
    class FakeBrowser:
        def new_page(self, **kwargs):
            return FakePage()
        def close(self):
            pass
    class FakePlaywright:
        def __init__(self):
            self.chromium = SimpleNamespace(launch=lambda **k: FakeBrowser())
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePlaywright())
    out = record_module.record(film_dir / "film.html", tmp_path / "film.mp4")
    assert out.exists()
    assert len(seen) == 1
    assert seen[0][-3:-1] == ["-f", "mp4"]
    assert seen[0][-1].endswith(".partial")


def test_n26_canonical_country_and_municipality_are_saved(tmp_path):
    """Stored research keeps no locale, only the season zone."""
    found = SimpleNamespace(name="Tower", kind="tower", qid="Q1", articles={}, municipality="SYNTHETIC_TOWN", country_code="gb")
    slug = cli.report_and_save(found, "en", [], [], [], [], {}, {}, "baseten", [], None, out_root=tmp_path, quiet=True)
    saved = json.loads((tmp_path / slug / "research.json").read_text())
    assert "municipality" not in saved["object"]
    assert "country_code" not in saved["object"]
    assert saved["object"]["season_zone"] == "north"


def test_n27_raw_source_prompts_lack_delimiters():
    """Every prompt delimits untrusted text as data, not instructions."""
    prompts = [captions.sentence_prompt("fact", "untrusted source", 1900), children.rewrite_prompt("adult", "untrusted source"), spot.spot_prompt(["untrusted source"])]
    assert all(verify.SOURCE_BEGIN in p and verify.SOURCE_END in p for p in prompts)
    assert all("instructions" in p for p in prompts)


def test_n28_computed_sort_year_becomes_anchor():
    """The anchor card shows the human label, never a sort key."""
    scene = evidence_scene(from_year=1026, date_label="around a thousand years ago")
    assert builder.anchor_card(scene)["label"] == "around a thousand years ago"


def test_n29_child_switch_resolves_assets_against_adult_page(tmp_path):
    """The player resolves the sibling film through its own page URL."""
    research = {"object": {"name": "Tower"}, "claims": [evidence_claim()],
                "scenes": [evidence_scene()]}
    film = builder.write_film(tmp_path / "job", research, {"1900": "e/1900.png"},
                              "today.jpg", "", sibling="child/film.json")
    saved = json.loads((film / "film.json").read_text())
    assert saved["sibling"] == "child/film.json"
    assert saved["sibling_page"] == "child/film.html"
    template = Path(builder.__file__).with_name("film.html").read_text()
    assert "sibling_page" in template
    assert "audienceTarget" in template


def test_n30_modal_dict_update_loses_concurrent_cancel(tmp_path):
    """A cancel landing mid-append survives on separate keys."""
    import modal_app
    store = modal_app.DictStore({})
    store.create_job("id", new_record(tmp_path, status="started"))
    raced = []
    class Racy(dict):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            if key == "id:events" and not raced:
                raced.append(True)
                modal_app.DictStore(self).set_cancel("id")
            return value
    store._dict = Racy(store._dict)
    store.append_event("id", {"event": "verifying"})
    assert raced == [True]
    assert store.is_cancelled("id") is True
    assert {"event": "verifying"} in store.get_job("id")["events"]


def test_n31_previous_day_ticket_releases_new_day_reservation(tmp_path, monkeypatch):
    """An old ticket reconciles against its own day only."""
    authority = models.BudgetAuthority(tmp_path, daily_cap_usd=0.10)
    current = [tmp_path / "day-one.json"]
    monkeypatch.setattr(authority, "_file", lambda: current[0])
    old = authority.reserve(0.10)
    current[0] = tmp_path / "day-two.json"
    authority.reserve(0.10)
    authority.reconcile(old, 0)
    assert authority.reserved_usd() == pytest.approx(0.10)


def test_n32_multipart_consumed_before_upload_size_gate(tmp_path, monkeypatch):
    """A declared oversize upload is refused before the body is read."""
    import asyncio
    monkeypatch.setattr(photo, "MAX_UPLOAD_BYTES", 8)
    store = webapp.MemoryStore()
    app = webapp.create_app(webapp.WebDeps(store, None, lambda _: None, tmp_path / "jobs", tmp_path / "examples"))
    body = (b'--synthetic\r\nContent-Disposition: form-data; name="ack"\r\n\r\non\r\n'
          b'--synthetic\r\nContent-Disposition: form-data; name="photo"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n' + b"X" * 65536 + b"\r\n--synthetic--\r\n")
    chunks = [body[i:i + 4096] for i in range(0, len(body), 4096)]
    count = [0]
    sent = []
    async def receive():
        if count[0] < len(chunks):
            chunk = chunks[count[0]]
            count[0] += 1
            return {"type": "http.request", "body": chunk, "more_body": count[0] < len(chunks)}
        await asyncio.sleep(0.01)
        return {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/jobs", "raw_path": b"/api/jobs", "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver"), (b"content-type", b"multipart/form-data; boundary=synthetic"),
                    (b"content-length", str(len(body)).encode("ascii"))],
        "server": ("testserver", 80), "client": ("synthetic-client", 1), "root_path": ""}
    asyncio.run(app(scope, receive, send))
    assert count[0] == 0
    assert next(m["status"] for m in sent if m["type"] == "http.response.start") == 400


def test_n33_search_snippets_crowd_out_real_fetched_evidence():
    """Snippets never enter the passage pool; fetched text does."""
    claim = evidence_claim(sources=[URL], visible_change="stone roof")
    jobs = cli.build_jobs([claim], {URL: QUOTE}, ["https://example.org/: snippet"] * 13, 1900)
    assert jobs
    assert jobs[0]["passages"]
    assert all(verify._fetched_para(p) is not None for p in jobs[0]["passages"])


def test_runner_failure_leaves_job_never_pruned(tmp_path):
    """A refused spawn still ends the job, so retention prunes it."""
    def boom(spec):
        raise RuntimeError("spawn refused")
    client, store = make_client(tmp_path, runner=boom)
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), "blue").save(buf, format="JPEG")
    posted = client.post("/api/jobs", data={"ack": "on"},
                         files={"photo": ("p.jpg", buf.getvalue(), "image/jpeg")},
                         headers={"Origin": "http://testserver"})
    assert posted.status_code == 500
    [job_id] = store.job_ids()
    assert store.get_job(job_id)["ended_at"] is not None
    assert webapp.prune_jobs(store, 10 ** 12) == 1
    assert list((tmp_path / "jobs").glob("job-*/today.jpg")) == []


def test_user_cancel_never_sets_ended_at_so_photo_kept_forever(tmp_path):
    """A user cancel ends the job, so retention prunes the photo."""
    client, store = make_client(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), "blue").save(buf, format="JPEG")
    posted = client.post("/api/jobs", data={"ack": "on"},
                         files={"photo": ("p.jpg", buf.getvalue(), "image/jpeg")},
                         headers={"Origin": "http://testserver"})
    assert posted.status_code == 200
    [job_id] = store.job_ids()
    assert client.delete(f"/api/jobs/{job_id}", headers={"Origin": "http://testserver"}).status_code == 200
    assert store.get_job(job_id)["ended_at"] is not None
    assert webapp.prune_jobs(store, 10 ** 12) == 1
    assert list((tmp_path / "jobs").glob("job-*/today.jpg")) == []


def test_end_card_lists_sources_of_claims_not_in_the_film():
    """The end card lists only sources behind filmed scenes."""
    shown = evidence_claim()
    trimmed = evidence_claim(claim="A trimmed era.", year=1930,
                             url="https://heritage-register.example/mill",
                             quote="A trimmed era quote long enough to stand.")
    sources = [entry["url"] for entry in builder.end_sources([evidence_scene()], [shown, trimmed])]
    assert URL in sources
    assert "https://heritage-register.example/mill" not in sources


def test_dictstore_loses_cancel_under_concurrent_progress():
    """A cancel racing a progress write survives on its own key."""
    import modal_app
    store = modal_app.DictStore({})
    store.create_job("j", {"vid": "v", "vkey": "k", "token": "t", "job_dir": "/jobs/j",
                           "status": "started", "events": [], "started_at": 0.0,
                           "last_poll": 0.0, "ended_at": None, "confirm": None,
                           "decision": None, "cancel": False, "result": None})
    cancelled_seen = []
    class Racy(dict):
        armed = True
        def __getitem__(self, key):
            value = super().__getitem__(key)
            if isinstance(value, dict):
                value = dict(value)
            if Racy.armed and key == "j:events":
                Racy.armed = False
                modal_app.DictStore(self).set_cancel("j")
                cancelled_seen.append(modal_app.DictStore(self).is_cancelled("j"))
            return value
    store._dict = Racy(store._dict)
    store.append_event("j", {"event": "verifying"})
    assert cancelled_seen == [True]
    assert store.is_cancelled("j") is True
    assert {"event": "verifying"} in store.get_job("j")["events"]


def test_r3_09_child_budget_failure_discards_ready_adult_result(tmp_path, monkeypatch):
    """A child cap failure still delivers the rendered adult film."""
    store = webapp.MemoryStore(clock=lambda: 1000)
    spec = {"job_id": "id", "token": "cap", "vid": "vid", "job_dir": str(tmp_path),
            "photo": "synthetic", "place": "", "location": None, "lat": None, "lon": None}
    store.create_job("id", {"vid": "vid", "job_dir": str(tmp_path), "status": "started",
                            "started_at": 1000, "last_poll": 1000})
    result = {"identified": True, "confirmed": True, "slug": "tower",
              "found": SimpleNamespace(name="Tower"), "order": [], "kept": [evidence_claim()],
              "timeline": [], "chosen": [evidence_scene()],
              "result": {"outcome": "full_film"}, "timings": {}, "failures": [],
              "comparison": None, "tokens": {}, "cost_usd": 0.01}
    monkeypatch.setattr(cli, "run_job", lambda *a, **kw: result)
    monkeypatch.setattr(cli, "report_and_save", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "cmd_captions", lambda *a, **kw: 0)
    monkeypatch.setattr(cli, "cmd_children", lambda *a, **kw: 0)
    def paint_call(*a, **kw):
        if kw.get("audience") == "child":
            raise models.SpendingCapExceeded("synthetic cap")
        return 0
    monkeypatch.setattr(cli, "cmd_paint", paint_call)
    seen = []
    monkeypatch.setattr(cli, "cmd_render", lambda *a, **kw: seen.append(True) or 0)
    answer = webfilm.run_web_film(spec, store, None, clock=lambda: 1000)
    assert answer["status"] == "film"
    assert seen
    finished = store.get_job("id")
    assert finished["result"]["film_url"].endswith("/film.html")
    assert finished["result"]["audiences"] == "adult"
    assert finished["result"]["unavailable"] == ["children"]


R3_14_HARNESS = r"""
const vm = require("vm");
const mode = process.argv[2];
const elements = {};
function el(id) { return elements[id] || (elements[id] = {style: {}, dataset: {}, textContent: "", children: [], appendChild(x) { this.children.push(x); }}); }
const statuses = [{status: "working", events: [{event: "painting", data: {}}], confirm: null},
  {status: "done", result: {message: "Facts below", claims: [{year: 1900, claim: "SYNTHETIC_FACT", url: "https://example.org/"}]}}];
let calls = 0;
async function fetch(url) {
  calls += 1;
  if (url === "/api/jobs") { return {json: async () => ({job_id: "id"})}; }
  if (mode === "flaky" && calls === 2) { throw new Error("synthetic network drop"); }
  if (mode === "http500") { return {ok: false, status: 500, json: async () => ({error: "boom"})}; }
  return {json: async () => statuses.shift()};
}
const context = {document: {getElementById: el, createElement: () => ({})}, navigator: {}, window: {addEventListener() {}},
  FormData: class {}, Date, setInterval: () => 1, clearInterval() {}, setTimeout: fn => fn(), alert: () => {}, fetch,
  console};
vm.createContext(context); vm.runInContext(SOURCE, context);
const phases = [];
{
  const box = el("events");
  let current = "";
  Object.defineProperty(box, "textContent", {get: () => current, set: v => { current = v; phases.push(v); }});
}
(async () => {
  await elements.upload.onsubmit({preventDefault() {}});
  const result = elements.result || {textContent: "", children: []};
  const links = (result.children || []).map(c => c.href || null);
  process.stdout.write(JSON.stringify({facts: result.textContent, phases, links}));
})().catch(e => { process.stderr.write(String(e)); process.exit(1); });
"""


def _run_r3_14_harness(tmp_path, mode):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = re.search(r'<script nonce="__NONCE__">(.*?)</script>', webapp.INDEX_PAGE, re.S).group(1)
    assert "innerHTML" not in script
    path = tmp_path / "ui.cjs"
    path.write_text("const SOURCE=" + json.dumps(script) + ";\n" + R3_14_HARNESS)
    result = subprocess.run([node, str(path), mode], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_r3_14_ui_hides_facts_and_progress_in_real_dom(tmp_path):
    """The page shows the phase words, the facts and their source links."""
    rendered = _run_r3_14_harness(tmp_path, "ok")
    assert "SYNTHETIC_FACT" in rendered["facts"]
    assert rendered["phases"]
    assert any("painting" in phase.lower() for phase in rendered["phases"])
    assert "https://example.org/" in rendered["links"]


def test_r3_14_failed_poll_recovers_and_http_error_shows(tmp_path):
    """A dropped poll is retried; a 500 shows a clear message."""
    recovered = _run_r3_14_harness(tmp_path, "flaky")
    assert "SYNTHETIC_FACT" in recovered["facts"]
    failed = _run_r3_14_harness(tmp_path, "http500")
    assert "500" in failed["facts"] or "went wrong" in failed["facts"]


def test_r3_02_anchor_accepts_another_building_without_a_vote():
    """An anchor sentence about another building falls through to votes."""
    quote = "The chapel was built in 1900 with a tiled roof."
    called = []
    def reject(prompt):
        called.append(prompt)
        return verify.text_answer(json.dumps({"verdict": "unsupported", "quote": "", "support": []}))
    result = verify.judge_claim(reject, {"claim": "The tower was built in 1900.", "year": 1900,
        "anchor": "build", "event": "built", "detail": "tower built", "votes": 3,
        "keywords": ["tower", "built"], "passages": [URL + "\n" + quote],
        "anchor_names": ["Tower", "tower"]}, dispute_check=lambda *a: False)
    assert called
    assert result["verdict"] == "unsupported"


def test_r3_04_anchor_drops_approximate_date():
    """An approximate date keeps its qualifier on the opening card."""
    card = builder.anchor_card({"from_year": 1900, "date_label": "around 1900"})
    assert card["label"] == "around 1900"


def test_r3_03_unverified_condition_reaches_adult_and_child_paint(tmp_path, monkeypatch):
    """An unsourced condition is reset before either painter sees it."""
    scene = evidence_scene(state={"condition": "burnt"})
    scene["caption_sentence"]["child"] = {"text": "I rose with a stone roof."}
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "research.json").write_text(json.dumps({"object": {"name": "Tower", "country_code": "gb"}, "claims": [evidence_claim()], "scenes": [scene]}))
    monkeypatch.setattr(cli, "photo_bytes_clean", lambda _: b"synthetic")
    monkeypatch.setattr(identify, "capture_month", lambda _: None)
    monkeypatch.setattr(paint, "paint_directives", lambda *a: {"season": "summer", "excluded": {}})
    seen = []
    def parallel(*args, **kwargs):
        seen.append((dict(args[2][0]["state"]), kwargs["audience"]))
        return [{"image": None, "verdict": "dropped", "attempts": 1, "note": "synthetic"}]
    monkeypatch.setattr(paint, "paint_parallel", parallel)
    monkeypatch.setattr(cli, "recover_or_retry", lambda *a, **k: a[8])
    deny = lambda _: answer("", verdict="unsupported")
    for audience in ("adult", "child"):
        assert cli.cmd_paint("synthetic", "unused", out_dir=tmp_path, audience=audience, photo_month=1, support_call=deny) == 0
    assert [state["condition"] for state, _ in seen] == ["standing", "standing"]


def test_r3_16_old_painting_survives_state_change_with_same_caption(tmp_path):
    """A painting whose state changed is dropped, never reused."""
    scene = evidence_scene(state={"condition": "burnt"})
    data = {"object": {"name": "Tower"}, "claims": [evidence_claim()], "scenes": [scene]}
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "research.json").write_text(json.dumps(data))
    (root / "paint_test.json").write_text(json.dumps({"eras": [{"year": 1900, "verdict": "matches", "attempts": 1, "caption": "I rose with a stone roof.", "file": "synthetic.webp"}]}))
    (root / "synthetic.webp").write_bytes(b"synthetic")
    cli.recheck_paintings(root, data, lambda *a: "MATCHES even though burnt.")
    manifest = json.loads((root / "paint_test.json").read_text())
    kept = [entry for entry in manifest["eras"] if entry["verdict"] in ("matches", "recovered")]
    assert kept == []


def test_r3_16_matching_binding_keeps_painting(tmp_path):
    """A painting whose binding still matches is kept without a recheck."""
    scene = evidence_scene()
    data = {"object": {"name": "Tower"}, "claims": [evidence_claim()], "scenes": [scene]}
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "research.json").write_text(json.dumps(data))
    state = scene["state"]
    binding = paint.painting_binding(state, "I rose with a stone roof.", scene["caption_sentence"]["evidence"])
    (root / "paint_test.json").write_text(json.dumps({"eras": [{"year": 1900, "verdict": "matches", "attempts": 1, "caption": "I rose with a stone roof.", "file": "synthetic.webp", "binding": binding}]}))
    (root / "synthetic.webp").write_bytes(b"synthetic")
    def fail(*args):
        raise AssertionError("no vision check needed")
    assert cli.recheck_paintings(root, data, fail) == [(1900, True)]
    manifest = json.loads((root / "paint_test.json").read_text())
    assert manifest["eras"][0]["verdict"] == "matches"


def test_r3_10_eval_counts_errors_as_correct_rejects():
    """The recorded Meta summary counts its five errors separately."""
    recorded = json.loads((Path(__file__).resolve().parent.parent / "eval" /
                           "support_results_2026-10-30.json").read_text())
    summary = recorded["summary"]["meta"]
    assert summary["errors"] == 5
    assert summary["right"] == 47


def test_r3_11_no_fresh_clone_example_assets(tmp_path, capsys):
    """Missing example films are skipped with a log line, not deployed."""
    import modal_app

    assert modal_app._volume_examples(tmp_path) == []
    assert capsys.readouterr().out.count("skipping") == 3
    remote = tmp_path / "examples" / "de-adriaan"
    remote.mkdir(parents=True)
    (remote / "film.html").write_text("<html>synthetic</html>")
    found = modal_app._volume_examples(tmp_path / "examples")
    assert [ex["slug"] for ex in found] == ["de-adriaan"]


def test_r3_12_readme_film_command_only_researches():
    """The README gives a venv sequence from photo to film.html."""
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    assert re.search(r"^python -m witness", readme, re.M) is None
    for line in (".venv/bin/python -m witness film",
                 ".venv/bin/python -m witness captions",
                 ".venv/bin/python -m witness paint",
                 ".venv/bin/python -m witness render",
                 "film/film.html"):
        assert line in readme, line
    evaluation = (root / "eval" / "README.md").read_text()
    assert ".venv/bin/python eval/run_support_eval.py --set support" in evaluation
    assert ".venv/bin/python eval/run_support_eval.py --set hard" in evaluation


def test_r3_22_real_looking_coordinate_literals_remain_in_tracked_tests():
    """Tracked tests use obvious placeholder coordinates, never real ones."""
    import ast

    root = Path(__file__).resolve().parent
    for name in ("test_webapp.py", "test_webfilm.py", "test_modal_app.py",
                 "test_identify.py"):
        text = (root / name).read_text()
        for literal in ("52.1235", "4.5678", "52.12346", "4.56784",
                        "52.123456", "4.987654", "4.9877"):
            assert literal not in text, (name, literal)
    tree = ast.parse((root / "test_webfilm.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value in ("lat", "lon")
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, float)):
                assert not (abs(value.value) > 1 and len(
                    str(value.value).split(".")[-1]) >= 3)


def test_r3_06_chunked_upload_stops_at_the_receive_cap(tmp_path, monkeypatch):
    """A chunked body past the cap is refused before it is fully read."""
    import asyncio

    from fastapi.testclient import TestClient  # noqa: F401 (client parity)

    monkeypatch.setattr(photo, "MAX_UPLOAD_BYTES", 8)
    deps = webapp.WebDeps(webapp.MemoryStore(), None, lambda _: None,
                           tmp_path / "jobs", tmp_path / "examples")
    app = webapp.create_app(deps)
    body = (b'--probe\r\nContent-Disposition: form-data; name="ack"\r\n\r\non\r\n'
            b'--probe\r\nContent-Disposition: form-data; name="photo"; filename="x.png"\r\n'
            b'Content-Type: image/png\r\n\r\n' + b'X' * 131072 + b'\r\n--probe--\r\n')
    chunks = [body[i:i + 4096] for i in range(0, len(body), 4096)]
    count = [0]
    sent = []

    async def receive():
        if count[0] < len(chunks):
            part = chunks[count[0]]
            count[0] += 1
            return {"type": "http.request", "body": part,
                    "more_body": count[0] < len(chunks)}
        await asyncio.sleep(.01)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/api/jobs",
             "raw_path": b"/api/jobs", "query_string": b"",
             "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver"),
                         (b"content-type", b"multipart/form-data; boundary=probe")],
             "server": ("testserver", 80), "client": ("synthetic-client", 1),
             "root_path": ""}
    asyncio.run(app(scope, receive, send))
    assert count[0] < len(chunks)
    assert next(m["status"] for m in sent
                if m["type"] == "http.response.start") == 400


def test_r3_18_broken_image_spends_no_quota(tmp_path):
    """A file that fails the full decode is refused before admission."""
    from fastapi.testclient import TestClient

    authority = models.BudgetAuthority(tmp_path / "budget", daily_films=10,
                                       visitor_films=2)
    deps = webapp.WebDeps(webapp.MemoryStore(), authority, lambda _: None,
                           tmp_path / "jobs", tmp_path / "examples")
    client = TestClient(webapp.create_app(deps),
                        raise_server_exceptions=False)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    damaged = buf.getvalue()[:45]
    photo.check_upload_header(damaged)
    for _ in range(2):
        response = client.post("/api/jobs", headers={"Origin": "http://testserver"},
                               files={"photo": ("x.png", damaged)},
                               data={"ack": "on"})
        assert response.status_code == 400
    assert authority.total_films() == 0
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    good = client.post("/api/jobs", headers={"Origin": "http://testserver"},
                       files={"photo": ("x.png", buf.getvalue())},
                       data={"ack": "on"})
    assert good.status_code == 200


def test_r3_08_missing_usage_charges_the_reserved_ceiling(tmp_path):
    """A response without usable usage is charged, not forgiven."""
    authority = models.BudgetAuthority(tmp_path / "budget",
                                       daily_cap_usd=10.0)
    models.configure_spending(authority=authority)
    calls = []
    fake = SimpleNamespace(responses=SimpleNamespace(
        create=lambda **kw: calls.append(kw) or {"output": []}))
    for _ in range(4):
        models.respond(fake, models.VERIFY, input="synthetic")
    payload = dict(calls[0])
    payload.pop("model", None)
    one = models.call_ceiling(
        models.VERIFY, models.estimate_input_tokens(payload))
    assert one > 0
    assert authority.total_usd() == pytest.approx(4 * one)
    assert authority.reserved_usd() == 0
    assert authority.snapshot()["calls"] == 4
    junk = SimpleNamespace(responses=SimpleNamespace(
        create=lambda **kw: {"output": [], "usage": "junk"}))
    models.respond(junk, models.VERIFY, input="synthetic")
    assert authority.total_usd() == pytest.approx(5 * one)
    zero = SimpleNamespace(responses=SimpleNamespace(
        create=lambda **kw: {"output": [],
                             "usage": {"prompt_tokens": 0,
                                       "completion_tokens": 0}}))
    models.respond(zero, models.VERIFY, input="synthetic")
    assert authority.total_usd() == pytest.approx(5 * one)


def test_r3_07_two_containers_with_the_shared_secret_agree(tmp_path):
    """Same shared secret on two instances: the visitor quota holds."""
    from fastapi.testclient import TestClient

    authority = models.BudgetAuthority(tmp_path / "budget", daily_films=10,
                                       visitor_films=2)
    secret = "shared-test-secret"
    one = TestClient(webapp.create_app(webapp.WebDeps(
        webapp.MemoryStore(), authority, lambda _: None,
        tmp_path / "one" / "jobs", tmp_path / "one" / "examples",
        ip_secret=secret)), raise_server_exceptions=False)
    two = TestClient(webapp.create_app(webapp.WebDeps(
        webapp.MemoryStore(), authority, lambda _: None,
        tmp_path / "two" / "jobs", tmp_path / "two" / "examples",
        ip_secret=secret)), raise_server_exceptions=False)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    shot = buf.getvalue()

    def upload(client):
        return client.post("/api/jobs",
                           headers={"Origin": "http://testserver"},
                           files={"photo": ("x.png", shot)},
                           data={"ack": "on"})

    assert upload(one).status_code == 200
    assert upload(one).status_code == 200
    assert upload(one).status_code == 429
    assert upload(two).status_code == 429
    assert authority.total_films() == 2
    assert webapp.visitor_key(secret, "synthetic-client", 7) != \
        webapp.visitor_key(secret, "synthetic-client", 8)


def test_r3_15_expired_film_and_photo_reads_refuse(tmp_path):
    """Past the retention deadline the film and photo read as gone."""
    import ast
    from fastapi.testclient import TestClient
    from pathlib import Path as _Path

    store = webapp.MemoryStore()
    now = [0.0]
    deps = webapp.WebDeps(store, None, lambda _: None,
                           tmp_path / "jobs", tmp_path / "examples",
                           clock=lambda: now[0])
    client = TestClient(webapp.create_app(deps),
                        raise_server_exceptions=False)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    response = client.post("/api/jobs", headers={"Origin": "http://testserver"},
                           files={"photo": ("x.png", buf.getvalue())},
                           data={"ack": "on"})
    assert response.status_code == 200
    job = store.get_job(response.json()["job_id"])
    film = _Path(job["job_dir"]) / "film"
    film.mkdir()
    (film / "today.jpg").write_bytes(buf.getvalue())
    route = f"/film/{response.json()['job_id']}/{job['token']}/today.jpg"
    assert client.get(route).status_code == 200
    store.end_job(response.json()["job_id"], "done", {"ended_at": 1})
    webapp.prune_jobs(store, 24 * 3600)
    assert (film / "today.jpg").exists()
    now[0] = 24 * 3600 + 2
    assert client.get(route).status_code == 404
    root = _Path(webapp.__file__).resolve().parent.parent
    assert "modal.Period(hours=1)" in (root / "modal_app.py").read_text()


def test_r3_20_ledger_visitor_hashes_expire_totals_stay():
    """The ledger scrub drops old visitor hashes and keeps the totals."""
    import ast
    from pathlib import Path as _Path

    import modal_app

    data = {"visitors": {
        "vid-old": {"n": 2, "at": 1000.0},
        "ip:old": {"n": 2, "at": 1000.0},
        "vid-fresh": {"n": 1, "at": 200000.0},
        "vid-legacy": 2},
        "films": 5, "calls": 9, "total_usd": 1.25, "reserved_usd": 0.5,
        "open": {"t1": 0.5}}
    data, answer = modal_app._apply_ledger_op(
        data, {"kind": "expire", "now": 1000.0 + 24 * 3600 + 1})
    assert answer["ok"] is True
    assert data["visitors"] == {"vid-fresh": {"n": 1, "at": 200000.0}}
    assert (data["films"], data["calls"], data["total_usd"],
            data["reserved_usd"], data["open"]) == (5, 9, 1.25, 0.5,
                                                   {"t1": 0.5})
    root = _Path(modal_app.__file__).resolve().parent
    tree = ast.parse((root / "modal_app.py").read_text())
    function = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "prune_hourly")
    names = {n.id for n in ast.walk(function)
             if isinstance(n, ast.Name)}
    assert "ledger_dict" in names


def test_r3_17_slow_drip_hits_the_total_deadline_fast(monkeypatch):
    """A dripping body fails at the deadline, not at the last byte."""
    import http.client
    import socket
    import threading
    import time as _time

    one, two = socket.socketpair()
    one.settimeout(.5)

    def server():
        with two:
            two.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n")
            for _ in range(12):
                _time.sleep(.02)
                try:
                    two.sendall(b"x")
                except OSError:
                    break

    thread = threading.Thread(target=server)
    thread.start()
    raw = http.client.HTTPResponse(one)
    raw.begin()
    response = web._PinnedResponse(SimpleNamespace(close=one.close), raw,
                                   "https://example.org/history")
    monkeypatch.setattr(web, "assert_public_url", lambda _: None)
    started = _time.monotonic()
    try:
        with pytest.raises(web.WebError):
            web.fetch_public("https://example.org/history",
                             sender=lambda *a, **kw: response,
                             total_timeout=.03)
        assert _time.monotonic() - started < .15
    finally:
        one.close()
        thread.join()


def test_r3_01_location_leaves_the_spec_on_worker_start(tmp_path,
                                                        monkeypatch):
    """Once the worker has started, spec.json has no location keys."""
    from fastapi.testclient import TestClient

    store = webapp.MemoryStore()

    def worker(ref):
        full = webfilm.load_spec(ref["job_dir"])
        webfilm.run_web_film(full, store, None)
        return "test-receipt"

    deps = webapp.WebDeps(store, None, worker, tmp_path / "jobs",
                           tmp_path / "examples")
    client = TestClient(webapp.create_app(deps),
                        raise_server_exceptions=False)
    monkeypatch.setattr(cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False,
                                         "cached": False,
                                         "error_kind": "quota",
                                         "error": "visitor quota spent"})
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    response = client.post("/api/jobs",
                           headers={"Origin": "http://testserver"},
                           files={"photo": ("x.png", buf.getvalue())},
                           data={"ack": "on", "place": "SYNTHETIC_PLACE",
                                 "lat": "0.5", "lon": "0.25"})
    assert response.status_code == 200
    job = store.get_job(response.json()["job_id"])
    spec = json.loads((Path(job["job_dir"]) / "spec.json").read_text())
    assert "place" not in spec and "location" not in spec
    assert "lat" not in spec and "lon" not in spec
    models.configure_spending(None)


def test_r3_13_repository_carries_its_licence():
    """The repo ships the MIT licence with the right holder and year."""
    from pathlib import Path as _Path

    root = _Path(webapp.__file__).resolve().parent.parent
    text = (root / "LICENSE").read_text()
    assert "MIT License" in text
    assert "2026 De Barbanson Data Solutions" in text


def test_r4_05_remote_example_layout_is_discovered(tmp_path):
    """Both apps discover examples from the Volume at request time."""
    import ast
    from fastapi.testclient import TestClient

    import modal_app

    tree = ast.parse(Path(modal_app.__file__).read_text())
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "EXAMPLES" not in assigned
    assert not hasattr(modal_app, "_available_examples")
    web = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == "web")
    names = {n.id for n in ast.walk(web) if isinstance(n, ast.Name)}
    assert "_volume_examples" in names
    remote = tmp_path / "examples"
    for slug in ("de-adriaan", "major-oak", "rubjerg-knude"):
        folder = remote / slug
        folder.mkdir(parents=True)
        (folder / "film.html").write_text("<html>synthetic</html>")
        (folder / "film.json").write_text("{}")
        (folder / "today.jpg").write_bytes(b"synthetic-today")
    found = modal_app._volume_examples(remote)
    assert [ex["slug"] for ex in found] == ["de-adriaan", "major-oak",
                                            "rubjerg-knude"]
    deps = webapp.WebDeps(webapp.MemoryStore(), None,
                           lambda ref: "test-receipt", tmp_path / "jobs",
                           remote, examples=found)
    client = TestClient(webapp.create_app(deps),
                        raise_server_exceptions=False)
    page = client.get("/")
    assert page.status_code == 200
    for slug in ("de-adriaan", "major-oak", "rubjerg-knude"):
        assert f"/examples/{slug}/" in page.text
        assert client.get(f"/examples/{slug}/").status_code == 200
        for asset in ("film.html", "film.json", "today.jpg"):
            out = client.get(f"/examples/{slug}/{asset}")
            assert out.status_code == 200, (slug, asset)


def test_r4_02_optional_deadline_keeps_the_published_adult(tmp_path,
                                                           monkeypatch):
    """A deadline in the extras keeps the published adult film."""
    from types import SimpleNamespace as _NS

    store = webapp.MemoryStore(clock=lambda: 1000)
    spec = {"job_id": "id", "token": "cap", "vid": "vid",
            "job_dir": str(tmp_path), "photo": "synthetic", "place": "",
            "location": None, "lat": None, "lon": None}
    store.create_job("id", {"vid": "vid", "job_dir": str(tmp_path),
                            "status": "started", "started_at": 1000,
                            "last_poll": 1000})
    result = {"identified": True, "confirmed": True, "slug": "tower",
              "found": _NS(name="Tower"), "order": [], "kept": [],
              "timeline": [], "chosen": [],
              "result": {"outcome": "full_film"}, "timings": {},
              "failures": [], "comparison": None, "tokens": {},
              "cost_usd": 0}
    monkeypatch.setattr(cli, "run_job", lambda *a, **kw: result)
    monkeypatch.setattr(cli, "report_and_save", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "cmd_captions", lambda *a, **kw: 0)
    monkeypatch.setattr(cli, "cmd_paint", lambda *a, **kw: 0)
    film = tmp_path / "tower" / "film" / "film.html"

    def render(*a, **kw):
        film.parent.mkdir(parents=True, exist_ok=True)
        film.write_text("<html>Synthetic adult film</html>")
        return 0

    monkeypatch.setattr(cli, "cmd_render", render)
    seen = []

    def extras(*a, **kw):
        seen.append((film.exists(),
                     bool((store.get_job("id").get("result") or {}).get(
                         "film_url"))))
        raise models.JobDeadlineExceeded("synthetic optional deadline")

    monkeypatch.setattr(cli, "cmd_children", extras)
    answer = webfilm.run_web_film(spec, store, None, clock=lambda: 1000)
    assert seen == [(True, True)]
    assert answer["status"] == "film"
    kept = store.get_job("id").get("result") or {}
    assert kept.get("film_url")
    assert "children" in kept.get("unavailable", [])


def test_r4_03_partial_damage_stays_partial():
    """Part-burnt evidence never paints as total destruction."""
    from witness import paint, states

    words = ("one wing of the tower was partly burnt in 1995; the rest "
             "survived. one wing was partly burnt in 1995, and the rest "
             "survived")
    assert states.traced_state("burnt", "total", "whole", words) == (
        "burnt", "partial", "part")
    prompt = paint.describe_state(
        "tower", {"condition": "burnt", "degree": "partial",
                  "scope": "part",
                  "description": "one wing blackened by fire"})
    assert "only the remains" not in prompt.lower()
    assert "part of tower is burnt" in prompt.lower()


def test_r4_03_supported_destruction_stays_total():
    """A claim of entire destruction keeps total and whole."""
    from witness import paint, states

    words = "the mill was destroyed entirely by fire"
    assert states.traced_state("burnt", "total", "whole", words) == (
        "burnt", "total", "whole")
    prompt = paint.describe_state(
        "mill", {"condition": "burnt", "degree": "total",
                 "scope": "whole", "description": "a burnt shell"})
    assert "only the remains" in prompt.lower()
