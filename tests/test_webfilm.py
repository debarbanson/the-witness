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
        assert order == ["save", "captions", "paint", "render"]
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
        assert result["cost_usd"] == 0.01 + 0.01
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


def test_quiet_tab_keeps_the_film(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    captured = []
    spec["on_cancel"] = captured.append

    def fake_run(*args, **kwargs):
        kwargs["progress"]("verifying", {})  # no poll for a long while
        models._check_control()
        return _confirmed_run()

    _phase2(monkeypatch, None)
    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None,
                            clock=lambda: 1000.0) == {"status": "film"}
    finally:
        models.configure_spending(None)
    assert not captured[0]._cancelled.is_set()
    assert store.get_job("job-1")["status"] == "done"


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
    spec.update({"lat": 0.5, "lon": 0.25})
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
    assert seen["location"] == (0.5, 0.25)
    assert seen["visitor"] == "visitor-1"


def test_scrub_hand_off_removes_location_keys_atomically(tmp_path):
    import json

    from witness.webfilm import scrub_hand_off

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    full = {"job_id": "job-1", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": "today.jpg",
            "place": "SYNTHETIC_PRIVATE_PLACE", "lat": 0.5, "lon": 0.25,
            "location": [0.5, 0.25]}
    (job_dir / "spec.json").write_text(json.dumps(full))
    assert scrub_hand_off(job_dir) is True
    scrubbed = json.loads((job_dir / "spec.json").read_text())
    assert scrubbed == {"job_id": "job-1", "token": "t", "vid": "v",
                        "job_dir": str(job_dir), "photo": "today.jpg"}
    assert sorted(p.name for p in job_dir.iterdir()) == ["spec.json"]
    assert scrub_hand_off(job_dir) is False


def test_scrub_hand_off_missing_file_is_a_noop(tmp_path):
    from witness.webfilm import scrub_hand_off

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    assert scrub_hand_off(job_dir) is False


def test_scrub_hand_off_deletes_an_unreadable_spec(tmp_path):
    import pytest

    from witness.webfilm import scrub_hand_off

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "spec.json").write_bytes(b"{not json")
    with pytest.raises(ValueError):
        scrub_hand_off(job_dir)
    assert not (job_dir / "spec.json").exists()


def test_run_web_film_scrubs_before_the_first_paid_call(tmp_path,
                                                        monkeypatch):
    import json

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    spec.update(place="SYNTHETIC_PRIVATE_PLACE", lat=0.5, lon=0.25,
                location=[0.5, 0.25])
    job_dir = tmp_path / "job"
    (job_dir / "spec.json").write_text(json.dumps(spec))

    def run_job(*args, **kwargs):
        on_disk = json.loads((job_dir / "spec.json").read_text())
        assert "place" not in on_disk and "location" not in on_disk
        assert "lat" not in on_disk and "lon" not in on_disk
        return {"confirmed": False, "identified": False, "cached": False,
                "error_kind": "quota", "error": "visitor quota spent"}

    monkeypatch.setattr(webfilm_module.cli, "run_job", run_job)
    try:
        assert run_web_film(spec, store, authority=None) == {
            "status": "refused"}
    finally:
        models.configure_spending(None)


def _full_film_result():
    from types import SimpleNamespace

    return {"identified": True, "confirmed": True, "slug": "job",
            "found": SimpleNamespace(name="Tower"), "order": [],
            "kept": [], "timeline": [], "chosen": [],
            "result": {"outcome": "full_film"}, "timings": {},
            "failures": [], "comparison": None, "tokens": {},
            "cost_usd": 0.0}


def test_declined_says_only_identification_ran(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": True,
                                         "cached": False})
    try:
        assert run_web_film(spec, store, authority=None) == {
            "status": "declined"}
    finally:
        models.configure_spending(None)
    message = store.get_job("job-1")["result"]["message"]
    assert "nothing spent" not in message.lower()
    assert "identification" in message.lower()
    assert "no research or painting was paid for" in message.lower()


def test_film_result_carries_per_call_timings(tmp_path, monkeypatch):
    import json

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)

    def fake_run(*args, **kwargs):
        client = models.client_for(models.VERIFY)
        models.respond(client, models.VERIFY, phase="verify",
                       input="Claim to check: secret-claim")
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
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        result = store.get_job("job-1")["result"]
        calls = result["timings"]["calls"]
        assert len(calls) == 1
        assert calls[0]["phase"] == "verify"
        assert calls[0]["offset_s"] >= 0
        assert "t" not in calls[0]
        dumped = json.dumps(calls)
        assert "secret-claim" not in dumped
        assert "http" not in dumped
    finally:
        models.configure_spending(None)


def test_paint_step_events_name_the_model(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

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
        events = {e["event"]: e.get("data", {})
                  for e in store.get_job("job-1")["events"]}
        assert events["captions"].get("model") == "Muse Spark"
        assert events["painting"].get("model") == "Muse Image"
    finally:
        models.configure_spending(None)


def _film_spec(tmp_path, monkeypatch):
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
    return store, spec


def test_upload_ends_at_adult_publication(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _film_spec(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: calls.append("captions") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                        lambda *a, **k: calls.append("paint") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                        lambda *a, **k: calls.append("render") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_children",
                        lambda *a, **k: calls.append("children") or 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_spot",
                        lambda *a, **k: calls.append("spot") or 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert calls == ["captions", "paint", "render"]
        job = store.get_job("job-1")
        assert job["status"] == "done"
        assert job["result"]["film_url"] == "/film/job-1/token-1/film.html"
    finally:
        models.configure_spending(None)


def test_published_adult_survives_cancel_deadline_and_error(
        tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    for case, boom in enumerate((models.JobCancelled("gone"),
                                models.JobDeadlineExceeded("slow"),
                                RuntimeError("disk"))):
        case_dir = tmp_path / f"case{case}"
        case_dir.mkdir(parents=True, exist_ok=True)
        store, spec = _film_spec(case_dir, monkeypatch)
        monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_children",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_spot",
                            lambda *a, **k: 0)

        def commit():
            raise boom

        try:
            assert run_web_film(spec, store, authority=None,
                                commit=commit) == {"status": "film"}
            job = store.get_job("job-1")
            assert job["status"] == "done"
            assert "film_url" in job["result"]
        finally:
            models.configure_spending(None)


def test_stale_heartbeat_does_not_cancel_the_film(tmp_path, monkeypatch):
    import time as _time

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _film_spec(tmp_path, monkeypatch)
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": True, "identified": True,
                                         "cached": False, "slug": "q1-mill",
                                         "found": SimpleNamespace(
                                             name="Mill", kind="mill",
                                             qid="Q1", articles={},
                                             municipality=None),
                                         "order": ["en"], "kept": [],
                                         "timeline": [], "chosen": [],
                                         "result": {"outcome": "short_film"},
                                         "timings": {}, "failures": [],
                                         "comparison": None, "tokens": {},
                                         "cost_usd": 0.01})
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    def paint_like_real(*args, **kwargs):
        models._check_control()
        return 0

    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", paint_like_real)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    store.jobs["job-1"]["last_poll"] = _time.time() - 300
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        assert store.get_job("job-1")["status"] == "done"
    finally:
        models.configure_spending(None)
