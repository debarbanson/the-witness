"""The private web page: upload, progress, capability films. No live calls."""

import io

from fastapi.testclient import TestClient
from PIL import Image

from witness import models
from witness.webapp import MemoryStore, WebDeps, create_app


def _photo_bytes(color="blue"):
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buf, format="JPEG")
    return buf.getvalue()


class FakeAuthority:
    def __init__(self):
        self.admitted = []

    def admit(self, visitor):
        self.admitted.append(visitor)

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
    return TestClient(create_app(_deps(tmp_path, **overrides)))


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
    assert ran[0]["photo"].endswith("today.jpg")
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
