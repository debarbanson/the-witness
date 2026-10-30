"""The private web page: upload, progress, capability films. No live calls."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from witness import models
from witness.webapp import MemoryStore, WebDeps, create_app

ORIGIN = {"Origin": "http://testserver"}


def _photo_bytes(color="blue"):
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buf, format="JPEG")
    return buf.getvalue()


class FakeAuthority:
    def __init__(self):
        self.admitted = []

    def admit(self, visitor, extra=None):
        self.admitted.append((visitor, extra))

    def reserve(self, ceiling_usd):
        return models.BudgetTicket(ceiling_usd)

    def reconcile(self, ticket, actual_usd):
        pass

    def total_usd(self):
        return 0.0


def _deps(tmp_path, **overrides):
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(exist_ok=True)
    examples_root = tmp_path / "examples"
    ada = examples_root / "de-adriaan"
    ada.mkdir(parents=True, exist_ok=True)
    (ada / "film.html").write_text(
        "<html><head></head><body><script>\n\"use strict\";\nplay();\n</script></body></html>")
    (ada / "film.json").write_text("{}")
    args = dict(store=MemoryStore(), authority=FakeAuthority(),
                runner=lambda spec: None,
                jobs_root=jobs_root, examples_root=examples_root,
                examples=[{"slug": "de-adriaan", "name": "De Adriaan"}],
                contact="owner@example.com", clock=lambda: 1000.0)
    args.update(overrides)
    return WebDeps(**args)


def _client(tmp_path, **overrides):
    return TestClient(create_app(_deps(tmp_path, **overrides)),
                      headers=dict(ORIGIN))


def test_index_shows_notice_examples_and_place_hint(tmp_path):
    out = _client(tmp_path).get("/")
    assert out.status_code == 200
    body = out.text
    for word in ("De Adriaan", "Meta", "Baseten", "Nominatim", "Overpass",
                 "Wikidata", "Wikipedia", "24", "owner@example.com",
                 "public places only"):
        assert word in body, word


def test_privacy_page_is_fuller(tmp_path):
    out = _client(tmp_path).get("/privacy")
    assert out.status_code == 200
    for section in ("What you send us", "Who processes it",
                    "How long it is kept", "Contact"):
        assert section in out.text
    assert "24 h" in out.text


def test_security_headers_on_every_response(tmp_path):
    client = _client(tmp_path)
    for path in ("/", "/privacy", "/examples/de-adriaan"):
        out = client.get(path)
        assert out.headers["Strict-Transport-Security"].startswith("max-age=")
        assert out.headers["X-Content-Type-Options"] == "nosniff"
        assert out.headers["Referrer-Policy"] == "no-referrer"
        csp = out.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'nonce-" in csp


def test_film_nonce_matches_its_header(tmp_path):
    out = _client(tmp_path).get("/examples/de-adriaan")
    csp = out.headers["Content-Security-Policy"]
    nonce = csp.split("script-src 'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in out.text


def test_upload_starts_a_job_and_runs_it(tmp_path):
    ran = []
    client = _client(tmp_path, runner=ran.append)
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on"})
    assert out.status_code == 200
    job_id = out.json()["job_id"]
    assert len(ran) == 1
    assert ran[0]["job_id"] == job_id
    assert set(ran[0]) == {"job_id", "job_dir"}
    import json
    spec = json.loads((tmp_path / "jobs" / ran[0]["job_dir"].split("/")[-1]
                       / "spec.json").read_text())
    assert spec["photo"].endswith("today.jpg")
    status = client.get(f"/api/jobs/{job_id}")
    assert status.json()["status"] == "started"
    assert status.json()["started_at"] == 1000.0
    assert "vid" in client.cookies


def test_upload_needs_ack_and_a_real_photo(tmp_path):
    client = _client(tmp_path)
    denied = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())})
    assert denied.status_code == 400
    bad = client.post("/api/jobs", files={"photo": ("up.jpg", b"junk" * 8)},
                      data={"ack": "on"})
    assert bad.status_code == 400


def test_upload_deletes_the_raw_file(tmp_path):
    client = _client(tmp_path, runner=lambda spec: None)
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on"})
    assert out.status_code == 200
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()
                 and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                 and p.name != "today.jpg"]
    assert leftovers == []


def test_location_never_reaches_the_store(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on", "place": "Synthetic Private Place",
                            "lat": "52.123456", "lon": "4.987654"})
    assert out.status_code == 200
    dump = repr(store.jobs)
    assert "Synthetic Private Place" not in dump
    assert "52.123456" not in dump
    assert "52.1235" not in dump


def test_job_status_needs_its_visitor(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    stranger = _client(tmp_path, store=store)
    out = stranger.get(f"/api/jobs/{job_id}")
    assert out.status_code == 403
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_clearing_confirm_keeps_status(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    store.create_job("j", {"status": "working", "confirm": {"name": "X"},
                           "decision": None, "cancel": False, "events": []})
    store.set_confirm("j", None)
    assert store.get_job("j")["confirm"] is None
    assert store.get_job("j")["status"] == "working"
    store.set_confirm("j", {"name": "X"})
    assert store.get_job("j")["status"] == "confirming"


def test_decide_and_cancel_round_trip(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/decide",
                       json={"confirm": True}).status_code == 200
    assert store.get_decision(job_id) is True
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert store.is_cancelled(job_id) is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"


def test_cross_origin_api_writes_are_refused(tmp_path):
    client = _client(tmp_path, runner=lambda spec: None)
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    evil = client.delete(f"/api/jobs/{job_id}",
                         headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403


def test_capability_film_needs_its_token(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    job = store.jobs[job_id]
    film_dir = job["job_dir"] + "/film"
    import os
    os.makedirs(film_dir, exist_ok=True)
    with open(film_dir + "/film.html", "w") as handle:
        handle.write("<html><script>\n\"use strict\";\n</script></html>")
    good = client.get(f"/film/{job_id}/{job['token']}/film.html")
    assert good.status_code == 200
    assert "nonce=" in good.text
    assert client.get(f"/film/{job_id}/wrong-token/film.html").status_code == 404
    assert client.get(f"/film/{job_id}/{job['token']}/../film.html").status_code == 404


def test_errors_are_sanitised_with_a_correlation_id(tmp_path):
    def boom(spec):
        raise RuntimeError("synthetic runner failure with details")

    client = _client(tmp_path, runner=boom)
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on"})
    assert out.status_code == 500
    body = out.json()
    assert body["error"] == "something went wrong"
    assert "synthetic" not in out.text
    assert body["correlation_id"]
    assert out.headers["X-Correlation-Id"] == body["correlation_id"]


def test_retention_deletes_old_jobs(tmp_path):
    import os
    from witness import webapp

    now = [200000.0]
    store = MemoryStore(clock=lambda: now[0])
    client = _client(tmp_path, store=store, runner=lambda spec: None,
                     clock=lambda: now[0])
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    job_dir = store.jobs[job_id]["job_dir"]
    assert os.path.isdir(job_dir)
    store.finish_job(job_id, {"outcome": "too_little"})
    now[0] += 25 * 3600  # retention time advanced past 24 h
    webapp.prune_jobs(store, now[0])
    assert job_id not in store.jobs
    assert not os.path.exists(job_dir)


def _upload(client, **data):
    fields = {"ack": "on"}
    fields.update(data)
    return client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                       data=fields, headers=ORIGIN)


def test_cancel_sets_ended_at_and_prunes(tmp_path):
    import os
    from witness import webapp

    now = [200000.0]
    store = MemoryStore(clock=lambda: now[0])
    client = _client(tmp_path, store=store, runner=lambda spec: None,
                     clock=lambda: now[0])
    job_id = _upload(client).json()["job_id"]
    assert client.delete(f"/api/jobs/{job_id}", headers=ORIGIN).status_code == 200
    assert store.get_job(job_id)["ended_at"] == 200000.0
    now[0] += 25 * 3600
    assert webapp.prune_jobs(store, now[0]) == 1
    assert job_id not in store.jobs


def test_spawn_failure_ends_the_job_with_headers(tmp_path):
    from witness import webapp

    def boom(spec):
        raise RuntimeError("spawn refused")

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=boom)
    out = _upload(client)
    assert out.status_code == 500
    assert out.headers["Content-Security-Policy"]
    assert out.headers["Strict-Transport-Security"]
    assert out.headers["X-Content-Type-Options"] == "nosniff"
    [job_id] = store.job_ids()
    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert job["ended_at"] is not None


def test_unfinished_jobs_prune_by_maximum_age(tmp_path):
    from witness import webapp

    store = MemoryStore()
    store.create_job("old", {"job_dir": str(tmp_path / "old"),
                             "status": "working", "started_at": 0.0,
                             "ended_at": None})
    store.create_job("fresh", {"job_dir": str(tmp_path / "fresh"),
                               "status": "working", "started_at": 100 * 3600.0,
                               "ended_at": None})
    assert webapp.prune_jobs(store, 100 * 3600.0 + 10) == 1
    assert store.job_ids() == ["fresh"]


def test_sweep_removes_orphaned_job_dirs_only(tmp_path):
    import os
    from witness import webapp

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    store = MemoryStore()
    known = jobs / "job-known"
    known.mkdir()
    (known / "today.jpg").write_bytes(b"x")
    store.create_job("known", {"job_dir": str(known), "status": "working",
                               "started_at": 100 * 3600.0, "ended_at": None})
    orphan = jobs / "job-orphan"
    orphan.mkdir()
    (orphan / "today.jpg").write_bytes(b"x")
    old = 100 * 3600.0 - webapp.MAX_JOB_AGE_SECONDS - 10
    os.utime(orphan / "today.jpg", (old, old))
    os.utime(orphan, (old, old))
    young = jobs / "job-young"
    young.mkdir()
    assert webapp.sweep_job_dirs(store, jobs, 100 * 3600.0) == 1
    assert not orphan.exists()
    assert (known / "today.jpg").exists()
    assert young.exists()


def test_oversize_body_refused_before_any_read(tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile

    from witness import webapp

    monkeypatch.setattr(webapp.photo_module, "MAX_UPLOAD_BYTES", 100_000)
    reads = []
    real_read = UploadFile.read

    async def spy(self, size=-1):
        reads.append(size)
        return await real_read(self, size)

    monkeypatch.setattr(UploadFile, "read", spy)
    client = _client(tmp_path, runner=lambda spec: None)
    big = b"\xff\xd8" + b"0" * 5_000_000
    out = client.post("/api/jobs", files={"photo": ("p.jpg", big, "image/jpeg")},
                      data={"ack": "on"}, headers=ORIGIN)
    assert out.status_code == 400
    assert reads == []
    assert list((tmp_path / "jobs").glob("job-*")) == []


def test_admission_runs_before_any_file_or_record(tmp_path):
    from witness import webapp

    class Full(FakeAuthority):
        def admit(self, visitor, extra=None):
            raise models.SpendingCapExceeded("daily quota")

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None,
                     authority=Full())
    out = _upload(client)
    assert out.status_code == 429
    assert "daily quota" in out.json()["error"]
    assert store.job_ids() == []
    assert list((tmp_path / "jobs").glob("job-*")) == []


def test_origin_must_match_exactly(tmp_path):
    client = _client(tmp_path, runner=lambda spec: None)
    job_id = _upload(client).json()["job_id"]
    evil = client.delete(f"/api/jobs/{job_id}",
                         headers={"Origin": "https://testserver.evil.example"})
    assert evil.status_code == 403
    bare = TestClient(create_app(_deps(tmp_path, store=MemoryStore(),
                                        runner=lambda spec: None)))
    missing = bare.delete(f"/api/jobs/{job_id}")
    assert missing.status_code == 403
    absent = client.delete("/api/jobs/nope",
                           headers={"Origin": "https://testserver.evil.example"})
    assert absent.status_code == 403
    assert client.delete(f"/api/jobs/{job_id}", headers=ORIGIN).status_code == 200


def test_visitor_ip_hash_limits_cookieless_uploads(tmp_path):
    from witness import webapp

    deps_store = MemoryStore()
    accepted, refused = [], []
    for _ in range(3):  # fresh client = no vid cookie, like curl
        client = TestClient(create_app(_deps(
            tmp_path, store=deps_store, authority=None,
            runner=lambda spec: None, ip_secret="test-secret")))
        out = _upload(client)
        (accepted if out.status_code == 200 else refused).append(out)
    assert len(accepted) == 2
    assert refused[0].status_code == 429
    records = [deps_store.get_job(j) for j in deps_store.job_ids()]
    assert len(records) == 2
    for record in records:
        assert len(record["vkey"]) == 64
        assert "testclient" not in str(record).lower().replace(
            record["job_dir"], "")


def test_visitor_key_rotates_daily_and_hides_the_ip():
    from witness import webapp

    first = webapp.visitor_key("secret", "198.51.100.7", "2026-10-30")
    assert first == webapp.visitor_key("secret", "198.51.100.7", "2026-10-30")
    assert first != webapp.visitor_key("secret", "198.51.100.7", "2026-10-31")
    assert first != webapp.visitor_key("other", "198.51.100.7", "2026-10-30")
    assert "198.51.100.7" not in first


def test_bad_lat_lon_rejected_before_any_file(tmp_path):
    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    for fields in ({"lat": "abc"}, {"lat": "52.1"}, {"lat": "999", "lon": "4.0"},
                   {"lat": "52.1", "lon": "abc"}):
        out = _upload(client, **fields)
        assert out.status_code == 400
    assert store.job_ids() == []
    assert list((tmp_path / "jobs").glob("job-*")) == []
    out = _upload(client, lat="52.12346", lon="4.56784")
    assert out.status_code == 200


def test_unhandled_errors_carry_headers_and_no_detail(tmp_path, monkeypatch):
    store = MemoryStore()

    def boom(job_id, record):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(store, "create_job", boom)
    client = TestClient(create_app(_deps(tmp_path, store=store)))
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on"}, headers=ORIGIN)
    assert out.status_code == 500
    assert out.headers["Content-Security-Policy"]
    assert out.headers["Strict-Transport-Security"]
    assert out.headers["X-Content-Type-Options"] == "nosniff"
    assert "exploded" not in out.text
    assert out.headers["X-Correlation-Id"] == out.json()["correlation_id"]


def test_403_refusals_carry_security_headers(tmp_path):
    client = _client(tmp_path, runner=lambda spec: None)
    out = client.delete("/api/jobs/nope",
                        headers={"Origin": "https://evil.example"})
    assert out.status_code == 403
    assert out.headers["Content-Security-Policy"]
    assert out.headers["X-Content-Type-Options"] == "nosniff"


def test_tab_close_cancel_path_and_heartbeat(tmp_path):
    from witness import webapp

    assert "pagehide" in webapp.INDEX_PAGE
    assert "sendBeacon" in webapp.INDEX_PAGE
    now = [1000.0]
    store = MemoryStore(clock=lambda: now[0])
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = _upload(client).json()["job_id"]
    assert store.last_poll(job_id) == 1000.0
    now[0] = 1100.0
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    assert store.last_poll(job_id) == 1100.0
    out = client.post(f"/api/jobs/{job_id}/cancel", headers=ORIGIN)
    assert out.status_code == 200
    assert store.is_cancelled(job_id) is True
    assert store.get_job(job_id)["ended_at"] == 1100.0


def test_runner_gets_a_reference_not_the_location(tmp_path):
    import json

    seen = []
    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=seen.append)
    job_id = _upload(client, place="Haarlem",
                     lat="52.12346", lon="4.56784").json()["job_id"]
    assert set(seen[0]) == {"job_id", "job_dir"}
    assert seen[0]["job_id"] == job_id
    job_dir = store.get_job(job_id)["job_dir"]
    spec = json.loads((tmp_path / "jobs" / job_dir.split("/")[-1]
                       / "spec.json").read_text())
    assert spec["place"] == "Haarlem"
    assert spec["lat"] == 52.1235
    assert spec["lon"] == 4.5678
    assert "Haarlem" not in str(store.get_job(job_id))


def test_privacy_notice_mentions_the_ip_hash():
    from witness import webapp

    assert "hash" in webapp.PRIVACY_PAGE
    assert "24 h" in webapp.PRIVACY_PAGE


def test_end_job_sets_status_result_and_end():
    store = MemoryStore(clock=lambda: 555.0)
    store.create_job("j", {"status": "working", "ended_at": None})
    store.end_job("j", "cancelled", {"message": "stopped"})
    job = store.get_job("j")
    assert (job["status"], job["result"]["message"], job["ended_at"]) == (
        "cancelled", "stopped", 555.0)
    store.finish_job("j", {"outcome": "film"})
    assert store.get_job("j")["status"] == "done"


def _style_blocks(page):
    blocks = []
    rest = page
    while "<style>" in rest:
        rest = rest.split("<style>", 1)[1]
        block, rest = rest.split("</style>", 1)
        blocks.append(block)
    return blocks


def test_csp_allows_only_hashed_styles(tmp_path):
    import base64
    import hashlib

    client = _client(tmp_path, runner=lambda spec: None)
    out = client.get("/")
    csp = out.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp
    assert 'style="' not in out.text
    blocks = _style_blocks(out.text)
    assert blocks
    for block in blocks:
        digest = base64.b64encode(
            hashlib.sha256(block.encode("utf-8")).digest()).decode("ascii")
        assert f"'sha256-{digest}'" in csp


def test_film_page_style_hash_matches(tmp_path):
    import base64
    import hashlib
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = _upload(client).json()["job_id"]
    job = store.jobs[job_id]
    film_dir = job["job_dir"] + "/film"
    import os
    os.makedirs(film_dir, exist_ok=True)
    css = "body{color:#fff}"
    with open(film_dir + "/film.html", "w") as handle:
        handle.write(f"<html><head><style>{css}</style></head><body>"
                     "<script>\n\"use strict\";\n</script></body></html>")
    out = client.get(f"/film/{job_id}/{job['token']}/film.html")
    assert out.status_code == 200
    csp = out.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp
    digest = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp


def test_no_inline_style_attributes_anywhere():
    from pathlib import Path

    import witness.render.builder as builder_module
    from witness import webapp

    assert 'style="' not in webapp.INDEX_PAGE
    templates = Path(builder_module.__file__).parent
    assert "style=" not in (templates / "film.html").read_text()
    assert "style=" not in (templates / "spot.html").read_text()


def test_job_status_reports_its_end(tmp_path):
    from witness.webapp import MemoryStore

    now = [1000.0]
    store = MemoryStore(clock=lambda: now[0])
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = _upload(client).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["ended_at"] is None
    client.delete(f"/api/jobs/{job_id}", headers=ORIGIN)
    assert client.get(f"/api/jobs/{job_id}").json()["ended_at"] == 1000.0
