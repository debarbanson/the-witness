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


def test_debug_endpoints_are_404_by_default(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/debug/ledger").status_code == 404
    assert client.post("/api/debug/reset-quotas").status_code == 404


def test_debug_endpoints_need_an_authority(tmp_path):
    client = _client(tmp_path, authority=None, debug_reset=True)
    assert client.get("/api/debug/ledger").status_code == 404
    assert client.post("/api/debug/reset-quotas").status_code == 404


def test_debug_reset_clears_quotas_and_ledger_reports_counts(tmp_path):
    auth = models.BudgetAuthority(tmp_path / "spend", daily_films=10,
                                  visitor_films=1)
    auth.admit("vid-a", extra="ip:hash-a")
    client = _client(tmp_path, authority=auth, debug_reset=True)
    before = client.get("/api/debug/ledger").json()
    assert before["films"] == 1 and before["visitors"] == 2
    assert "vid-a" not in str(before)
    assert client.post("/api/debug/reset-quotas").status_code == 200
    after = client.get("/api/debug/ledger").json()
    assert after["films"] == 0 and after["visitors"] == 0
    auth.admit("vid-a", extra="ip:hash-a")


def test_refused_upload_consumes_no_quota(tmp_path):
    from witness import photo as photo_module
    from witness import webapp as webapp_module

    auth = FakeAuthority()
    client = _client(tmp_path, authority=auth)
    over = photo_module.MAX_UPLOAD_BYTES + 100  # past the handler spool
    body = b"\xff\xd8" + b"0" * over  # under the middleware cap
    assert len(body) < (photo_module.MAX_UPLOAD_BYTES
                        + webapp_module.FORM_SLACK_BYTES)
    out = client.post("/api/jobs", files={"photo": ("p.jpg", body)},
                      data={"ack": "on"})
    assert out.status_code == 400, out.text[:200]
    bad = client.post("/api/jobs", files={"photo": ("up.jpg", b"junk" * 64)},
                      data={"ack": "on"})
    assert bad.status_code == 400, bad.text[:200]
    assert auth.admitted == []


def test_debug_reset_requires_origin(tmp_path):
    auth = models.BudgetAuthority(tmp_path / "spend", daily_films=10,
                                  visitor_films=2)
    bare = TestClient(create_app(_deps(tmp_path, authority=auth,
                                       debug_reset=True)))
    assert bare.post("/api/debug/reset-quotas").status_code == 403


class FakeAuthority:
    def __init__(self):
        self.admitted = []
        self.released = []

    def admit(self, visitor, extra=None):
        self.admitted.append((visitor, extra))

    def release(self, visitor, extra=None):
        self.released.append((visitor, extra))

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
    body = out.text.lower()
    for word in ("de adriaan", "meta", "baseten", "openstreetmap services",
                 "wikidata", "wikipedia", "24", "owner@example.com",
                 "public places only"):
        assert word in body, word


def test_privacy_page_is_fuller(tmp_path):
    out = _client(tmp_path).get("/privacy")
    assert out.status_code == 200
    for section in ("What you send us", "Who processes it",
                    "How long it is kept", "Contact"):
        assert section in out.text
    assert "24 h" in out.text


def test_privacy_page_keeps_one_quiet_age_sentence(tmp_path):
    out = _client(tmp_path).get("/privacy")
    assert out.status_code == 200
    assert out.text.count("You must be 18 or older to upload a photo.") == 1
    assert "For adults 18 and over" not in out.text
    assert "children's version" not in out.text.lower()
    assert "8+" not in out.text


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
                            "lat": "12.345678", "lon": "65.432164"})
    assert out.status_code == 200
    dump = repr(store.jobs)
    assert "Synthetic Private Place" not in dump
    assert "12.345678" not in dump
    assert "12.3457" not in dump


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


def test_failed_spawn_refunds_the_quota_but_a_start_counts(tmp_path):
    def boom(spec):
        raise RuntimeError("spawn refused")

    authority = FakeAuthority()
    store = MemoryStore()
    client = _client(tmp_path, store=store, authority=authority,
                     runner=boom)
    assert _upload(client).status_code == 500
    assert len(authority.admitted) == 1
    assert authority.released == authority.admitted
    good = FakeAuthority()
    store2 = MemoryStore()
    client2 = _client(tmp_path, store=store2, authority=good,
                      runner=lambda spec: "receipt")
    assert _upload(client2).status_code == 200
    assert len(good.admitted) == 1
    assert good.released == []


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
    error = out.json()["error"]
    assert "Daily limit" in error
    assert "Resets tomorrow" in error
    assert "examples" in error.lower()
    assert store.job_ids() == []
    assert list((tmp_path / "jobs").glob("job-*")) == []


def test_quota_errors_name_the_limit_and_point_to_examples(tmp_path):
    from witness import models

    for quota, needle in (("visitor quota", "Browser limit"),
                          ("network quota", "Network limit")):
        class Full(FakeAuthority):
            def admit(self, visitor, extra=None):
                raise models.SpendingCapExceeded(quota)

        client = _client(tmp_path, store=MemoryStore(),
                         runner=lambda spec: None, authority=Full())
        error = _upload(client).json()["error"]
        assert needle in error
        assert "Resets tomorrow" in error
        assert "examples" in error.lower()


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
    out = _upload(client, lat="12.34567", lon="65.43214")
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


def test_only_the_cancel_button_cancels(tmp_path):
    from witness import webapp

    assert "pagehide" not in webapp.INDEX_PAGE
    assert "sendBeacon" not in webapp.INDEX_PAGE
    now = [1000.0]
    store = MemoryStore(clock=lambda: now[0])
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = _upload(client).json()["job_id"]
    assert store.last_poll(job_id) == 1000.0
    now[0] = 1100.0
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    assert store.last_poll(job_id) == 1100.0
    now[0] = 5000.0  # a quiet tab never cancels
    assert store.is_cancelled(job_id) is False
    out = client.delete(f"/api/jobs/{job_id}", headers=ORIGIN)
    assert out.status_code == 200
    assert store.is_cancelled(job_id) is True
    assert store.get_job(job_id)["ended_at"] == 5000.0


def test_runner_gets_a_reference_not_the_location(tmp_path):
    import json

    seen = []
    store = MemoryStore()
    client = _client(tmp_path, store=store,
                     runner=lambda ref: seen.append(ref) or "test-receipt")
    job_id = _upload(client, place="Haarlem",
                     lat="12.34567", lon="65.43214").json()["job_id"]
    assert set(seen[0]) == {"job_id", "job_dir"}
    assert seen[0]["job_id"] == job_id
    job_dir = store.get_job(job_id)["job_dir"]
    spec = json.loads((tmp_path / "jobs" / job_dir.split("/")[-1]
                       / "spec.json").read_text())
    assert spec["place"] == "Haarlem"
    assert spec["lat"] == 12.3457
    assert spec["lon"] == 65.4321
    assert "Haarlem" not in str(store.get_job(job_id))


def test_privacy_notice_names_modal_as_processor():
    from witness import webapp

    assert "Modal" in webapp.PRIVACY_PAGE


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


def test_film_route_serves_the_rendered_slug_directory(tmp_path):
    """The worker renders job_dir/<slug>/film; the capability route
    must serve that directory, HTML plus every asset, not job_dir/film."""
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = client.post(
        "/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
        data={"ack": "on"}).json()["job_id"]
    job = store.jobs[job_id]
    film_dir = tmp_path / "jobs" / job["job_dir"].split("/")[-1] / "q1-mill" / "film"
    (film_dir / "child").mkdir(parents=True)
    (film_dir / "film.html").write_text(
        "<html><body><script>\n\"use strict\";\n</script></body></html>")
    (film_dir / "film.json").write_text("{\"scenes\": []}")
    (film_dir / "today.jpg").write_bytes(b"fake-photo")
    (film_dir / "era_1900.webp").write_bytes(b"fake-era")
    (film_dir / "child" / "film.html").write_text("<html>child</html>")
    store.jobs[job_id]["film_dir"] = str(film_dir)
    base = f"/film/{job_id}/{job['token']}"
    assert client.get(base + "/film.html").status_code == 200
    assert client.get(base + "/film.json").json() == {"scenes": []}
    assert client.get(base + "/today.jpg").content == b"fake-photo"
    assert client.get(base + "/era_1900.webp").content == b"fake-era"
    assert client.get(base + "/child/film.html").status_code == 200


def test_film_route_finds_one_rendered_slug_without_stored_dir(tmp_path):
    """Records that predate film_dir storage still resolve: one job
    directory holds exactly one rendered film."""
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda spec: None)
    job_id = client.post(
        "/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
        data={"ack": "on"}).json()["job_id"]
    job = store.jobs[job_id]
    nested = tmp_path / "jobs" / job["job_dir"].split("/")[-1] / "q1-mill" / "film"
    nested.mkdir(parents=True)
    (nested / "film.html").write_text("<html>film</html>")
    assert "film_dir" not in store.jobs[job_id]
    out = client.get(f"/film/{job_id}/{job['token']}/film.html")
    assert out.status_code == 200


def test_example_url_has_a_trailing_slash(tmp_path):
    """The example page lives at the slashed URL so relative assets
    resolve inside the example."""
    from urllib.parse import urljoin

    client = _client(tmp_path)
    bare = client.get("/examples/de-adriaan", follow_redirects=False)
    assert bare.status_code in (301, 307, 308)
    assert bare.headers["location"].endswith("/examples/de-adriaan/")
    page = client.get("/examples/de-adriaan/")
    assert page.status_code == 200
    assert client.get(urljoin(str(page.url), "film.json")).status_code == 200


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


def test_upload_form_dependency_is_declared_for_fresh_clones():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    deps = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert any(d.split()[0].split(";")[0] == "python-multipart" for d in deps)


def _spec_of(tmp_path, store, job_id):
    import json

    job_dir = store.get_job(job_id)["job_dir"]
    return json.loads((tmp_path / "jobs" / job_dir.split("/")[-1]
                       / "spec.json").read_text())


def test_unconfirmed_spawn_scrubs_location_from_spec(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=lambda ref: None)
    out = _upload(client, place="SYNTHETIC_PRIVATE_PLACE", lat="0.5",
                  lon="0.25")
    assert out.status_code == 200
    spec = _spec_of(tmp_path, store, out.json()["job_id"])
    assert "place" not in spec and "location" not in spec
    assert "lat" not in spec and "lon" not in spec
    assert spec["photo"].endswith("today.jpg")


def test_confirmed_spawn_keeps_the_hand_off_for_the_worker(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    client = _client(tmp_path, store=store,
                     runner=lambda ref: "test-receipt")
    out = _upload(client, place="SYNTHETIC_PRIVATE_PLACE", lat="0.5",
                  lon="0.25")
    assert out.status_code == 200
    spec = _spec_of(tmp_path, store, out.json()["job_id"])
    assert spec["place"] == "SYNTHETIC_PRIVATE_PLACE"
    assert spec["lat"] == 0.5 and spec["lon"] == 0.25


def test_failed_spawn_scrubs_location_from_spec(tmp_path):
    from witness.webapp import MemoryStore

    def spawn(ref):
        raise RuntimeError("synthetic spawn failure")

    store = MemoryStore()
    client = _client(tmp_path, store=store, runner=spawn)
    out = _upload(client, place="SYNTHETIC_PRIVATE_PLACE", lat="0.5",
                  lon="0.25")
    assert out.status_code == 500
    job_id = store.job_ids()[0]
    spec = _spec_of(tmp_path, store, job_id)
    assert "place" not in spec and "location" not in spec
    assert "lat" not in spec and "lon" not in spec
    assert store.get_job(job_id)["status"] == "failed"


def test_privacy_notice_renders_the_contact(tmp_path):
    client = _client(tmp_path)
    notice = client.get("/privacy").text
    assert "owner@example.com" in notice
    assert "__CONTACT__" not in notice
    index = client.get("/").text
    assert "owner@example.com" in index
    assert "__CONTACT__" not in index


def test_try_switch_off_refuses_new_jobs_with_503(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    authority = FakeAuthority()
    client = _client(tmp_path, store=store, authority=authority,
                     try_enabled=lambda: False)
    out = _upload(client)
    assert out.status_code == 503
    assert "Try your own is resting; the examples are below" in out.text
    assert store.job_ids() == []
    assert authority.admitted == []


def test_try_switch_on_serves_jobs_and_off_serves_examples(tmp_path):
    from witness.webapp import MemoryStore

    store = MemoryStore()
    flag = {"on": True}
    client = _client(tmp_path, store=store,
                     runner=lambda ref: "test-receipt",
                     try_enabled=lambda: flag["on"])
    assert _upload(client).status_code == 200
    flag["on"] = False
    assert _upload(client).status_code == 503
    assert client.get("/").status_code == 200
    assert client.get("/examples/de-adriaan/").status_code == 200


def test_noindex_header_only_when_enabled(tmp_path):
    plain = _client(tmp_path)
    assert "x-robots-tag" not in plain.get("/").headers
    hidden = _client(tmp_path, noindex=True)
    for response in (hidden.get("/"), hidden.get("/privacy"),
                     hidden.get("/examples/de-adriaan/"),
                     hidden.get("/no-such-page")):
        assert response.headers["x-robots-tag"] == "noindex"
    denied = hidden.post("/api/jobs", files={"photo": ("up.jpg", b"x")},
                         data={"ack": "on"}, headers=ORIGIN)
    assert denied.headers["x-robots-tag"] == "noindex"


def test_robots_txt_disallows_everything(tmp_path):
    out = _client(tmp_path).get("/robots.txt")
    assert out.status_code == 200
    assert "User-agent: *" in out.text
    assert "Disallow: /" in out.text


def _prune_fixture(tmp_path, name):
    from witness import webapp
    from witness.webapp import MemoryStore

    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    now = 300000.0
    old_end = now - 25 * 3600
    old_start = now - 26 * 3600

    def job_dir(job_id):
        folder = root / job_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "today.jpg").write_bytes(b"photo")
        return str(folder)

    jobs = {}
    for job_id, status in (("done-1", "done"), ("cancel-1", "cancelled"),
                           ("fail-1", "failed")):
        jobs[job_id] = {"job_dir": job_dir(job_id), "status": status,
                        "started_at": old_start, "ended_at": old_end,
                        "events": []}
    jobs["lost-1"] = {"job_dir": job_dir("lost-1"), "status": "working",
                      "started_at": old_start, "ended_at": None, "events": []}
    jobs["fresh-1"] = {"job_dir": job_dir("fresh-1"), "status": "working",
                       "started_at": now - 60, "ended_at": None, "events": []}
    for job_id, record in jobs.items():
        store.create_job(job_id, {"vid": "v", **record})
    orphan = root / "orphan-1"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "today.jpg").write_bytes(b"photo")
    import os

    old = now - 26 * 3600
    os.utime(orphan, (old, old))
    return store, root, now


def test_prune_deletes_all_ended_states_and_never_ended(tmp_path):
    import os
    from witness import webapp

    for backend in ("staging", "judge"):
        store, root, now = _prune_fixture(tmp_path, backend)
        assert webapp.prune_jobs(store, now) == 4
        for job_id in ("done-1", "cancel-1", "fail-1", "lost-1"):
            assert job_id not in store.jobs
            assert not os.path.exists(root / job_id)
        assert "fresh-1" in store.jobs
        assert os.path.isdir(root / "fresh-1")
        assert webapp.sweep_job_dirs(store, str(root), now) == 1
        assert not os.path.exists(root / "orphan-1")


def test_prune_keeps_the_record_when_deletion_fails(tmp_path, capsys):
    from witness import webapp
    from witness.webapp import MemoryStore

    store = MemoryStore()
    now = 300000.0
    blocker = tmp_path / "not-a-dir.jpg"
    blocker.write_bytes(b"photo")
    store.create_job("stuck-1", {"vid": "v", "job_dir": str(blocker),
                                 "status": "done",
                                 "started_at": now - 26 * 3600,
                                 "ended_at": now - 25 * 3600,
                                 "events": []})
    assert webapp.prune_jobs(store, now) == 0
    assert "stuck-1" in store.jobs
    assert "stuck-1" in capsys.readouterr().out


def test_prune_commits_before_dropping_any_record(tmp_path):
    from witness import webapp
    from witness.webapp import MemoryStore

    store = MemoryStore()
    now = 300000.0
    for job_id in ("gone-1", "gone-2"):
        job_dir = tmp_path / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "today.jpg").write_bytes(b"photo")
        store.create_job(job_id, {"vid": "v", "job_dir": str(job_dir),
                                 "status": "done",
                                 "started_at": now - 26 * 3600,
                                 "ended_at": now - 25 * 3600,
                                 "events": []})
    seen = []

    def commit():
        seen.append(sorted(store.job_ids()))
        assert not (tmp_path / "gone-1").exists()
        assert not (tmp_path / "gone-2").exists()

    assert webapp.prune_jobs(store, now, commit=commit) == 2
    assert seen == [["gone-1", "gone-2"]]
    assert store.job_ids() == []


def test_prune_keeps_every_record_when_the_commit_fails(tmp_path):
    import pytest

    from witness import webapp
    from witness.webapp import MemoryStore

    store = MemoryStore()
    now = 300000.0
    job_dir = tmp_path / "gone-1"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "today.jpg").write_bytes(b"photo")
    store.create_job("gone-1", {"vid": "v", "job_dir": str(job_dir),
                               "status": "done",
                               "started_at": now - 26 * 3600,
                               "ended_at": now - 25 * 3600,
                               "events": []})

    def commit():
        raise OSError("synthetic volume commit failure")

    with pytest.raises(OSError):
        webapp.prune_jobs(store, now, commit=commit)
    assert store.job_ids() == ["gone-1"]


def test_sweep_counts_only_successful_deletions(tmp_path, monkeypatch):
    import shutil
    from witness import webapp
    from witness.webapp import MemoryStore

    store = MemoryStore()
    now = 300000.0
    root = tmp_path / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    orphan = root / "orphan-9"
    orphan.mkdir(parents=True, exist_ok=True)
    import os

    old = now - 26 * 3600
    os.utime(orphan, (old, old))
    real_rmtree = shutil.rmtree

    def boom(path, **kwargs):
        raise OSError("synthetic disk error")

    monkeypatch.setattr(shutil, "rmtree", boom)
    assert webapp.sweep_job_dirs(store, str(root), now) == 0
    assert orphan.is_dir()
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert webapp.sweep_job_dirs(store, str(root), now) == 1
    assert not orphan.exists()


def test_privacy_notice_states_both_retention_windows(tmp_path):
    out = _client(tmp_path).get("/privacy")
    assert out.status_code == 200
    assert "24 h" in out.text
    assert "25 h" in out.text


def test_landing_quota_line_is_cached_per_minute(tmp_path, monkeypatch):
    from witness import webapp as webapp_module

    calls = []
    real = webapp_module._quota_line

    def counting(deps, vid, vkey, now):
        calls.append(1)
        return real(deps, vid, vkey, now)

    monkeypatch.setattr(webapp_module, "_quota_line", counting)
    client = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200
    assert len(calls) == 1


def test_landing_hides_quota_line_when_unavailable(tmp_path, monkeypatch):
    from witness import webapp as webapp_module

    def boom(deps, vid, vkey, now):
        raise OSError("synthetic ledger outage")

    monkeypatch.setattr(webapp_module, "_quota_line", boom)
    out = _client(tmp_path).get("/")
    assert out.status_code == 200
    assert "tries a day" not in out.text


def test_landing_hides_quota_line_on_authority_error(tmp_path):
    """r6_03 made safe: a real authority outage hides the line; the
    job-store count never stands in for the ledger."""
    from witness import webapp as webapp_module

    class BrokenAuthority(FakeAuthority):
        daily_films = 10
        visitor_films = 2
        network_films = 2

        def quota(self, *args, **kwargs):
            raise OSError("synthetic ledger outage")

    deps = _deps(tmp_path, authority=BrokenAuthority())
    assert webapp_module._quota_line_cached(deps, "v", "k", 1000.0) == ""
    assert deps.quota_cache == {}
    client = TestClient(create_app(deps), headers=dict(ORIGIN))
    out = client.get("/")
    assert out.status_code == 200
    assert "Films left today" not in out.text


def test_quota_cache_evicts_expired_and_stays_bounded(tmp_path):
    """r6_04 made safe: expired entries leave on the next write and
    cookie churn cannot grow the cache past its bound."""
    from witness import webapp as webapp_module

    class CountingAuthority(FakeAuthority):
        daily_films = 10
        visitor_films = 2
        network_films = 2

        def __init__(self):
            super().__init__()
            self.calls = 0

        def quota(self, *args, **kwargs):
            self.calls += 1
            return {"films": 0, "visitor": 0, "network": 0}

    authority = CountingAuthority()
    deps = _deps(tmp_path, authority=authority)
    bound = webapp_module.QUOTA_LINE_CACHE_MAX
    for index in range(bound + 50):
        webapp_module._quota_line_cached(
            deps, f"visitor-{index}", "k", 1000.0)
    assert authority.calls == bound + 50
    assert len(deps.quota_cache) <= bound
    webapp_module._quota_line_cached(deps, "fresh", "k",
                                     1000.0 + 61.0)
    assert len(deps.quota_cache) <= bound
    assert all(expires > 1000.0 + 61.0
               for _, expires in deps.quota_cache.values())


def test_quota_cache_survives_concurrent_page_views(tmp_path):
    """The web containers take concurrent requests: hammer the
    per-visitor cache from threads; every view gets a line, the
    cache stays bounded, nothing raises."""
    import threading

    from witness import webapp as webapp_module

    class CountingAuthority(FakeAuthority):
        daily_films = 10
        visitor_films = 2
        network_films = 2

        def quota(self, *args, **kwargs):
            return {"films": 0, "visitor": 0, "network": 0}

    deps = _deps(tmp_path, authority=CountingAuthority())
    errors = []
    lines = []

    def view(index):
        try:
            lines.append(webapp_module._quota_line_cached(
                deps, f"visitor-{index % 40}", "k", 1000.0))
        except Exception as exc:  # noqa: BLE001 - collected, then raised
            errors.append(exc)

    threads = [threading.Thread(target=view, args=(index,))
               for index in range(200)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(lines) == 200
    assert all("Films left today" in line for line in lines)
    assert len(deps.quota_cache) <= webapp_module.QUOTA_LINE_CACHE_MAX


def test_concurrent_uploads_are_capped_per_container(tmp_path):
    from fastapi.testclient import TestClient

    from witness.webapp import create_app
    from witness import webapp as webapp_module

    deps = _deps(tmp_path)
    client = TestClient(create_app(deps), headers=dict(ORIGIN))
    slots = deps.upload_slots
    for _ in range(webapp_module.MAX_CONCURRENT_UPLOADS):
        assert slots.acquire(blocking=False)
    try:
        out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                          data={"ack": "on"})
        assert out.status_code == 503, out.text[:200]
    finally:
        for _ in range(webapp_module.MAX_CONCURRENT_UPLOADS):
            slots.release()
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                      data={"ack": "on"})
    assert out.status_code == 200, out.text[:200]


def test_cancel_on_a_finished_job_keeps_the_film(tmp_path):
    from fastapi.testclient import TestClient

    from witness.webapp import MemoryStore, create_app

    store = MemoryStore()
    client = TestClient(create_app(_deps(tmp_path, store=store)),
                        headers=dict(ORIGIN))
    job_id = client.post("/api/jobs", files={"photo": ("up.jpg", _photo_bytes())},
                         data={"ack": "on"}).json()["job_id"]
    store.finish_job(job_id, {"film_url": "/film/x/film.html"})
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["result"]["film_url"] == "/film/x/film.html"
