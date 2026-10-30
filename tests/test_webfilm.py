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
                "kept": [{"year": 1850, "claim": "stood",
                          "verdict": "supported",
                          "url": "https://a.example/x",
                          "quote": "The mill stood in 1850."},
                         {"year": 1860, "claim": "bombed",
                          "verdict": "supported",
                          "war_politics_only": True,
                          "url": "https://a.example/y",
                          "quote": "The mill was bombed in 1860."},
                         {"year": 1870, "claim": "maybe",
                          "verdict": "unsupported",
                          "url": "https://a.example/z",
                          "quote": "Nothing here."}],
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
        assert result["claims"] == [
            {"year": 1850, "claim": "stood",
             "url": "https://a.example/x",
             "quote": "The mill stood in 1850."}]
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
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        result = store.get_job("job-1")["result"]
        assert result["film_url"] == "/film/job-1/token-1/film.html"
    finally:
        models.configure_spending(None)


def test_captions_run_before_paint(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)
    order = []

    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": found, "order": ["en"],
                "kept": [], "timeline": [], "chosen": [],
                "result": {"outcome": "short_film"}, "timings": {},
                "failures": [], "comparison": None, "tokens": {},
                "cost_usd": 0.01}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: order.append("save") or "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: order.append("captions") or 0)
    monkeypatch.setattr(
        webfilm_module.cli, "cmd_paint",
        lambda *a, **k: order.append(
            "child_paint" if k.get("audience") == "child" else "paint") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children",
                        lambda *a, **k: order.append("children") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot",
                        lambda *a, **k: order.append("spot") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                        lambda *a, **k: order.append("render") or 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert order == ["save", "captions", "paint", "children",
                         "child_paint", "spot", "render"]
    finally:
        models.configure_spending(None)


def _film_run(found):
    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": found, "order": ["en"],
                "kept": [], "timeline": [], "chosen": [],
                "result": {"outcome": "short_film"}, "timings": {},
                "failures": [], "comparison": None, "tokens": {},
                "cost_usd": 0.01}
    return fake_run


def _mill():
    return SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                           articles={}, municipality=None)


def test_child_set_runs_before_render(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    seen = {}
    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)

    def paint(*args, **kwargs):
        seen[kwargs.get("audience", "adult")] = args
        return 0

    def children(*args, **kwargs):
        seen["children"] = args
        return 0

    def spot(*args, **kwargs):
        seen["spot"] = args
        return 0

    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", paint)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children", children)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot", spot)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert set(seen) == {"adult", "child", "children", "spot"}
        assert seen["child"][0] == "q1-mill"
        assert store.get_job("job-1")["result"]["audiences"] == "both"
    finally:
        models.configure_spending(None)


def test_failed_children_still_ships_the_adult_film(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    rendered = []
    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children", lambda *a, **k: 2)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                        lambda *a, **k: rendered.append(a) or 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert rendered != []
        assert store.get_job("job-1")["result"]["audiences"] == "adult"
    finally:
        models.configure_spending(None)


def test_failed_child_paint_still_ships_the_adult_film(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(
        webfilm_module.cli, "cmd_paint",
        lambda *a, **k: 2 if k.get("audience") == "child" else 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert store.get_job("job-1")["result"]["audiences"] == "adult"
    finally:
        models.configure_spending(None)


def test_film_cost_covers_captions_paint_and_render(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)

    def paint(*args, **kwargs):
        models.note_usage("meta", {}, model="muse-image-1.0")
        return 0

    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", paint)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        result = store.get_job("job-1")["result"]
        assert result["cost_usd"] == 0.01 + 2 * 0.01
    finally:
        models.configure_spending(None)


def test_failed_captions_fall_back_to_facts(tmp_path, monkeypatch):
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
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 2)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "facts_only"}
        assert "captions failed" in store.get_job("job-1")["result"]["message"]
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
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 2)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "facts_only"}
        assert "painting failed" in store.get_job("job-1")["result"]["message"]
    finally:
        models.configure_spending(None)


def _confirmed_run(**overrides):
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)
    result = {"confirmed": True, "identified": True, "cached": False,
              "slug": "q1-mill", "found": found, "order": ["en"], "kept": [],
              "timeline": [], "chosen": [],
              "result": {"outcome": "short_film"}, "timings": {},
              "failures": [], "comparison": None, "tokens": {},
              "cost_usd": 0.01}
    result.update(overrides)
    return result


def _phase2(monkeypatch, run_result, captions=0, paint=0):
    import witness.webfilm as webfilm_module

    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: run_result)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: captions)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                        paint if callable(paint) else lambda *a, **k: paint)


def test_cancel_after_research_ends_cancelled(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    captured = []
    spec["on_cancel"] = captured.append

    def paint(*args, **kwargs):  # visitor cancels while painting
        captured[0].cancel()
        models._check_control()
        return 0

    _phase2(monkeypatch, _confirmed_run(), paint=paint)
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "cancelled"}
    finally:
        models.configure_spending(None)
    job = store.get_job("job-1")
    assert job["status"] == "cancelled"
    assert job["ended_at"] == 1000.0


def test_deadline_after_research_ends_expired(tmp_path, monkeypatch):
    def paint(*args, **kwargs):
        raise models.JobDeadlineExceeded("job deadline passed")

    _phase2(monkeypatch, _confirmed_run(), paint=paint)
    store, spec = _store(), _spec(tmp_path)
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "expired"}
    finally:
        models.configure_spending(None)
    job = store.get_job("job-1")
    assert job["status"] == "expired"
    assert job["ended_at"] == 1000.0


def test_runner_exception_ends_failed_not_crash(tmp_path, monkeypatch):
    def paint(*args, **kwargs):
        raise RuntimeError("synthetic paint explosion")

    _phase2(monkeypatch, _confirmed_run(), paint=paint)
    store, spec = _store(), _spec(tmp_path)
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "failed"}
    finally:
        models.configure_spending(None)
    job = store.get_job("job-1")
    assert job["status"] == "failed"
    assert job["ended_at"] == 1000.0


def test_phase1_cancel_sets_ended_at(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False, "cached": False,
                                         "cancelled": True,
                                         "error": "job cancelled"})
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "cancelled"}
    finally:
        models.configure_spending(None)
    assert store.get_job("job-1")["ended_at"] == 1000.0


def test_stale_heartbeat_cancels_before_paid_calls(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    captured = []
    spec["on_cancel"] = captured.append

    def fake_run(*args, **kwargs):
        kwargs["progress"]("verifying", {})  # no poll for a long while
        models._check_control()
        return _confirmed_run()

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "cancelled"}
    finally:
        models.configure_spending(None)
    assert captured[0]._cancelled.is_set()
    assert store.get_job("job-1")["ended_at"] == 1000.0


def test_confirmed_event_names_the_object_after_decision(tmp_path, monkeypatch):
    import threading
    import time

    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill")

    def answer():
        time.sleep(0.2)
        store.set_decision("job-1", True)

    threading.Thread(target=answer, daemon=True).start()

    def fake_run(*args, **kwargs):
        assert kwargs["decide"](found) is True
        return _confirmed_run()

    _phase2(monkeypatch, None)
    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children",
                        lambda *a, **k: 2)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None)["status"] == "film"
    finally:
        models.configure_spending(None)
    confirmed = [event for event in store.get_job("job-1")["events"]
                 if event["event"] == "confirmed"]
    assert confirmed == [{"t": confirmed[0]["t"], "event": "confirmed",
                          "data": {"name": "Mill", "kind": "mill"}}]


def test_quota_decline_and_miss_all_set_ended_at(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    cases = [
        ({"confirmed": False, "identified": False, "cached": False,
          "error_kind": "quota", "error": "visitor quota spent"}, "refused"),
        ({"confirmed": False, "identified": True, "cached": False}, "declined"),
        ({"confirmed": False, "identified": False, "cached": False}, "not_identified"),
    ]
    base = _spec(tmp_path)
    for index, (result, status) in enumerate(cases):
        store = _store()
        job_dir = tmp_path / f"job-{index}"
        job_dir.mkdir()
        spec = dict(base)
        spec["job_dir"] = str(job_dir)
        monkeypatch.setattr(webfilm_module.cli, "run_job",
                            lambda *a, **k: dict(result))
        try:
            assert run_web_film(spec, store, authority=None,
                                clock=lambda: 1000.0) == {"status": status}
        finally:
            models.configure_spending(None)
        assert store.get_job("job-1")["ended_at"] == 1000.0


def test_web_runner_passes_pre_admission_and_browser_location(
        tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    spec.update({"lat": 52.1235, "lon": 4.5678})
    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return {"confirmed": False, "identified": False, "cached": False}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    try:
        run_web_film(spec, store, authority=None)
    finally:
        models.configure_spending(None)
    assert seen["pre_admitted"] is True
    assert seen["location"] == (52.1235, 4.5678)
    assert seen["visitor"] == "visitor-1"
