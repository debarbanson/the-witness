"""The web film runner: every outcome lands honestly in the store."""

from types import SimpleNamespace

from witness import models
from witness.webapp import MemoryStore
from witness.webfilm import run_web_film


def _spec(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    return {"job_id": "job-1", "token": "token-1", "vid": "visitor-1",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "", "location": None}


def _store():
    store = MemoryStore()
    store.create_job("job-1", {"vid": "visitor-1", "token": "token-1",
                               "job_dir": "/tmp/job", "status": "started",
                               "events": [], "started_at": 0.0,
                               "ended_at": None, "confirm": None,
                               "decision": None, "cancel": False,
                               "result": None})
    return store


def test_quota_refusal_lands_honestly(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False, "cached": False,
                                         "error_kind": "quota",
                                         "error": "visitor quota spent"})
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "refused"}
        assert "quota" in store.get_job("job-1")["result"]["message"]
    finally:
        models.configure_spending(None)


def test_cancelled_job_marks_cancelled(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False, "cached": False,
                                         "cancelled": True,
                                         "error": "job cancelled"})
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "cancelled"}
        assert store.get_job("job-1")["status"] == "cancelled"
    finally:
        models.configure_spending(None)


def test_thin_evidence_returns_facts_only(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)

    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": found, "order": ["en"],
                "kept": [{"year": 1850, "claim": "stood"}],
                "timeline": [], "chosen": [],
                "result": {"outcome": "too_little"}, "timings": {},
                "failures": [], "comparison": None, "tokens": {},
                "cost_usd": 0.01}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "facts_only"}
        result = store.get_job("job-1")["result"]
        assert result["claims"] == [{"year": 1850, "claim": "stood"}]
        assert "Too little" in result["message"]
    finally:
        models.configure_spending(None)


def test_film_outcome_returns_capability_url(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)

    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": found, "order": ["en"],
                "kept": [], "timeline": [], "chosen": [],
                "result": {"outcome": "short_film"}, "timings": {},
                "failures": [], "comparison": None, "tokens": {},
                "cost_usd": 0.01}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        result = store.get_job("job-1")["result"]
        assert result["film_url"] == "/film/job-1/token-1/film.html"
    finally:
        models.configure_spending(None)


def test_paint_failure_falls_back_to_facts(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)

    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": found, "order": ["en"],
                "kept": [{"year": 1850, "claim": "stood"}],
                "timeline": [], "chosen": [],
                "result": {"outcome": "short_film"}, "timings": {},
                "failures": [], "comparison": None, "tokens": {},
                "cost_usd": 0.01}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 2)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "facts_only"}
        assert "painting failed" in store.get_job("job-1")["result"]["message"]
    finally:
        models.configure_spending(None)
