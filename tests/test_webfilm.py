"""The web film runner: every outcome lands honestly in the store."""

from types import SimpleNamespace

import pytest

from witness import models
from witness.webapp import MemoryStore
from witness.webfilm import run_web_film


@pytest.fixture(autouse=True)
def _no_website_lookup(monkeypatch):
    import witness.webfilm as webfilm_module

    monkeypatch.setattr(webfilm_module.cli.identify, "official_website",
                        lambda *a, **k: None)


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
        assert "about Mill" in result["message"]
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


def test_confirm_payload_carries_the_place_description(tmp_path, monkeypatch):
    import threading
    import time

    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Poldertoren", kind="water tower",
                            description="water tower in Noordoostpolder")
    seen = {}

    def answer():
        time.sleep(0.2)
        store.set_decision("job-1", True)

    threading.Thread(target=answer, daemon=True).start()

    def fake_run(*args, **kwargs):
        assert kwargs["decide"](found) is True
        seen["confirm"] = store.get_job("job-1")["confirm"]
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
    assert seen["confirm"] == {"name": "Poldertoren", "kind": "water tower",
                               "description": "water tower in Noordoostpolder"}


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


def test_full_fake_upload_verifies_a_fact_with_no_network(tmp_path, monkeypatch):
    import socket
    import threading
    import time

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Fake Mill", kind="mill", qid=None,
                            articles={}, municipality=None,
                            country_code="us", description="")
    monkeypatch.setattr(webfilm_module.cli.identify, "identify",
                        lambda *a, **k: found)
    monkeypatch.setattr(
        webfilm_module.cli, "film_facts",
        lambda *a, **k: {"facts": {"facts": []}, "claims": [],
                         "build_anchor_year": None})
    kept_seen = {}

    def save_spy(found, lang, order, kept, *args, **kwargs):
        kept_seen["kept"] = kept
        return "out/fake-mill"

    monkeypatch.setattr(webfilm_module.cli, "report_and_save", save_spy)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)

    def dead_socket(*args, **kwargs):
        raise AssertionError("the fake film must not touch the network")

    monkeypatch.setattr(socket, "socket", dead_socket)
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)

    def answer():
        time.sleep(0.2)
        store.set_decision("job-1", True)

    threading.Thread(target=answer, daemon=True).start()
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
    finally:
        models.configure_spending(None)
    job = store.get_job("job-1")
    assert job["status"] == "done"
    assert "film_url" in job["result"]
    from witness.verify import filmed

    assert [c for c in kept_seen["kept"] if filmed(c)], kept_seen["kept"]
    assert 0 < job["result"]["cost_usd"] < 0.05


def test_full_fake_upload_with_anchor_still_reaches_a_film(tmp_path, monkeypatch):
    import socket
    import threading
    import time

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Fake Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None,
                            country_code="us", description="")
    monkeypatch.setattr(webfilm_module.cli.identify, "identify",
                        lambda *a, **k: found)
    anchor_claim = {"year": 1792, "event": "built", "kind": "object",
                    "claim": "built 1792", "quote_span": None,
                    "date_text": "1792", "visible_change": "",
                    "sources": ["https://www.wikidata.org/wiki/Q1"]}
    monkeypatch.setattr(
        webfilm_module.cli, "film_facts",
        lambda *a, **k: {"facts": {"facts": []}, "claims": [anchor_claim],
                         "build_anchor_year": 1792})
    kept_seen = {}

    def save_spy(found, lang, order, kept, *args, **kwargs):
        kept_seen["kept"] = kept
        return "out/fake-mill"

    monkeypatch.setattr(webfilm_module.cli, "report_and_save", save_spy)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)

    def dead_socket(*args, **kwargs):
        raise AssertionError("the fake film must not touch the network")

    monkeypatch.setattr(socket, "socket", dead_socket)
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)

    def answer():
        time.sleep(0.2)
        store.set_decision("job-1", True)

    threading.Thread(target=answer, daemon=True).start()
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
    finally:
        models.configure_spending(None)
    job = store.get_job("job-1")
    assert job["status"] == "done"
    assert "film_url" in job["result"]
    from witness.verify import filmed

    filmed_years = {c["year"] for c in kept_seen["kept"] if filmed(c)}
    assert 1850 not in {c["year"] for c in kept_seen["kept"]}, \
        "the anchor must drop the research built year"
    assert filmed_years == {1900, 1925, 1950}, filmed_years
    assert 0 < job["result"]["cost_usd"] < 0.05


def test_fake_film_emits_safe_call_events(tmp_path, monkeypatch):
    import json
    import socket
    import threading
    import time

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Fake Mill", kind="mill", qid=None,
                            articles={}, municipality=None,
                            country_code="us", description="")
    monkeypatch.setattr(webfilm_module.cli.identify, "identify",
                        lambda *a, **k: found)
    monkeypatch.setattr(
        webfilm_module.cli, "film_facts",
        lambda *a, **k: {"facts": {"facts": []}, "claims": [],
                         "build_anchor_year": None})
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/fake-mill")
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)

    def dead_socket(*args, **kwargs):
        raise AssertionError("the fake film must not touch the network")

    monkeypatch.setattr(socket, "socket", dead_socket)
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)

    def answer():
        time.sleep(0.2)
        store.set_decision("job-1", True)

    threading.Thread(target=answer, daemon=True).start()
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
    finally:
        models.configure_spending(None)
    calls = [event for event in store.get_job("job-1")["events"]
             if event["event"] == "call"]
    assert calls, "the toggle needs rows while the job runs"
    for event in calls:
        assert set(event["data"]) <= {"op", "phase", "provider", "model",
                                     "duration_s"}, event["data"]
    dumped = json.dumps(calls)
    assert "http" not in dumped
    assert "data:image" not in dumped
    assert "MODEL_API_KEY" not in dumped
    assert "BASETEN_API_KEY" not in dumped


def test_not_identified_without_location_hints_at_where_is_it(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    spec["lat"], spec["lon"] = 52.0, 4.0  # browser fix, like the owner run
    assert spec["place"] in ("", None) and spec["location"] is None
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False})
    try:
        assert run_web_film(spec, store, authority=None)["status"] == "not_identified"
    finally:
        models.configure_spending(None)
    assert store.get_job("job-1")["result"]["message"] == (
        "We couldn't tell which landmark this is. Type its name and "
        "town under 'Where is it?' and try again.")


def test_not_identified_with_a_place_keeps_the_short_hint(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _store(), _spec(tmp_path)
    spec["place"] = "Test Town"
    monkeypatch.setattr(webfilm_module.cli, "run_job",
                        lambda *a, **k: {"confirmed": False,
                                         "identified": False})
    try:
        assert run_web_film(spec, store, authority=None)["status"] == "not_identified"
    finally:
        models.configure_spending(None)
    assert "Where is it" not in store.get_job("job-1")["result"]["message"]


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


def test_film_commits_before_done_is_visible(tmp_path, monkeypatch):
    """Commit-first publication: at commit time the film files exist
    but no poller can see done; only then is the URL published."""
    from pathlib import Path

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _film_spec(tmp_path, monkeypatch)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                        lambda *a, **k: 0)

    def render(slug, photo, **kwargs):
        film_dir = (Path(spec["job_dir"]) / slug / "film")
        film_dir.mkdir(parents=True, exist_ok=True)
        (film_dir / "film.html").write_text("synthetic complete film")
        return 0

    monkeypatch.setattr(webfilm_module.cli, "cmd_render", render)
    seen = []

    def commit():
        job = store.get_job("job-1")
        seen.append(job["status"])
        assert job["status"] != "done"
        assert "film_url" not in (job["result"] or {})
        assert (Path(spec["job_dir"]) / "q1-mill" / "film" / "film.html"
                ).exists()

    try:
        assert run_web_film(spec, store, authority=None,
                            commit=commit) == {"status": "film"}
        assert seen == ["working"]
        job = store.get_job("job-1")
        assert job["status"] == "done"
        assert job["result"]["film_url"] == "/film/job-1/token-1/film.html"
    finally:
        models.configure_spending(None)


def test_failed_first_commit_never_publishes_the_film(tmp_path, monkeypatch):
    """A commit failure means no durable film: no done, no URL."""
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    for case, boom in enumerate((OSError("synthetic failed commit"),
                                RuntimeError("synthetic disk fault"))):
        case_dir = tmp_path / f"case{case}"
        case_dir.mkdir(parents=True, exist_ok=True)
        store, spec = _film_spec(case_dir, monkeypatch)
        monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                            lambda *a, **k: 0)

        def commit():
            raise boom

        try:
            assert run_web_film(spec, store, authority=None,
                                commit=commit) == {"status": "failed"}
            job = store.get_job("job-1")
            assert job["status"] == "failed"
            assert "film_url" not in job["result"]
        finally:
            models.configure_spending(None)


def test_cancel_during_first_commit_leaves_no_film(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    cases = ((models.JobCancelled("gone"), "cancelled"),
             (models.JobDeadlineExceeded("slow"), "expired"))
    for index, (boom, status) in enumerate(cases):
        case_dir = tmp_path / f"case{index}"
        case_dir.mkdir(parents=True, exist_ok=True)
        store, spec = _film_spec(case_dir, monkeypatch)
        monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                            lambda *a, **k: 0)
        monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                            lambda *a, **k: 0)

        def commit():
            raise boom

        try:
            assert run_web_film(spec, store, authority=None,
                                commit=commit) == {"status": status}
            job = store.get_job("job-1")
            assert job["status"] == status
            assert "film_url" not in job["result"]
        finally:
            models.configure_spending(None)


def test_terminated_first_commit_never_publishes_the_film(tmp_path,
                                                          monkeypatch):
    import pytest

    import witness.webfilm as webfilm_module
    from witness.webfilm import run_web_film

    store, spec = _film_spec(tmp_path, monkeypatch)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                        lambda *a, **k: 0)

    def commit():
        raise SystemExit("synthetic worker termination")

    try:
        with pytest.raises(SystemExit):
            run_web_film(spec, store, authority=None, commit=commit)
        job = store.get_job("job-1")
        assert job["status"] != "done"
        assert "film_url" not in (job["result"] or {})
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


def _research_with_captions():
    claim = {"year": 1850, "url": "https://a.example/mill",
             "claim": "The mill stood.", "quote": "The mill stood in 1850.",
             "verdict": "supported"}
    return {
        "claims": [claim],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "caption_sentence": {
                 "text": "The mill stood tall.", "claim_year": 1850,
                 "evidence": {"claim": "The mill stood.",
                              "url": "https://a.example/mill",
                              "quote": "The mill stood in 1850."}}},
            {"from_year": 1900, "date_label": "1900"},
        ],
    }


def test_painting_start_publishes_checked_facts(tmp_path, monkeypatch):
    import json as _json
    import pathlib as _pathlib

    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)

    def save(*args, **kwargs):
        slug_dir = _pathlib.Path(spec["job_dir"]) / "q1-mill"
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "research.json").write_text(
            _json.dumps(_research_with_captions()))
        return str(slug_dir)

    def paint(*args, **kwargs):
        kwargs["progress"]("painted", {"year": 1850, "verdict": "matches",
                                       "accepted": 1, "dropped": 0,
                                       "attempted": 1})
        return 0

    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save", save)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint", paint)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        events = [(row["event"], row.get("data") or {})
                  for row in store.get_job("job-1")["events"]]
        facts = [data for event, data in events if event == "checked_facts"]
        assert len(facts) == 1
        assert facts[0]["items"] == [
            {"stamp": "1850", "text": "The mill stood tall.",
             "url": "https://a.example/mill"}]
        kinds = [event for event, _ in events]
        assert kinds.index("checked_facts") < kinds.index("painted")
        painted = [data for event, data in events if event == "painted"]
        assert painted == [{"year": 1850, "verdict": "matches",
                            "accepted": 1, "dropped": 0, "attempted": 1}]
    finally:
        models.configure_spending(None)


def test_real_paint_reports_facts_then_the_counter(tmp_path, monkeypatch):
    import io
    import json as _json
    import pathlib as _pathlib

    import witness.webfilm as webfilm_module
    from PIL import Image

    store, spec = _store(), _spec(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(buf, "PNG")
    photo = buf.getvalue()
    _pathlib.Path(spec["photo"]).write_bytes(photo)

    def save(*args, **kwargs):
        slug_dir = _pathlib.Path(spec["job_dir"]) / "q1-mill"
        slug_dir.mkdir(parents=True, exist_ok=True)
        data = _research_with_captions()
        data["object"] = {"name": "Mill"}
        data["photo_month"] = 5
        (slug_dir / "research.json").write_text(_json.dumps(data))
        return str(slug_dir)

    monkeypatch.setattr(webfilm_module.cli, "run_job", _film_run(_mill()))
    monkeypatch.setattr(webfilm_module.cli, "report_and_save", save)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions", lambda *a, **k: 0)
    monkeypatch.setattr(
        webfilm_module.cli, "paint_respond",
        lambda prompt, prev_id, photo_bytes=None: {
            "image": photo, "response_id": "r-x"})

    def look(image, prompt):
        if prompt.startswith("Look at this"):
            return "Season: summer\nNone"
        return "MATCHES whole mill."

    monkeypatch.setattr(webfilm_module.cli, "check_respond", look)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render", lambda *a, **k: 0)
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        events = [(row["event"], row.get("data") or {})
                  for row in store.get_job("job-1")["events"]]
        kinds = [event for event, _ in events]
        assert kinds.index("checked_facts") < kinds.index("painted")
        facts = [data for event, data in events if event == "checked_facts"]
        assert facts[0]["items"] == [
            {"stamp": "1850", "text": "The mill stood tall.",
             "url": "https://a.example/mill"}]
        painted = [data for event, data in events if event == "painted"]
        assert painted[-1] == {"year": 1850, "verdict": "matches",
                               "accepted": 1, "dropped": 0, "attempted": 1}
        assert (_pathlib.Path(spec["job_dir"]) / "q1-mill"
                / "eras_parallel" / "1850.webp").exists()
    finally:
        models.configure_spending(None)


def _too_little_run(kept, failures, read):
    def fake_run(*args, **kwargs):
        return {"confirmed": True, "identified": True, "cached": False,
                "slug": "q1-mill", "found": _mill(), "order": ["en"],
                "kept": kept, "timeline": [], "chosen": [],
                "result": {"outcome": "too_little"}, "timings": {},
                "failures": failures, "read": read,
                "comparison": None, "tokens": {}, "cost_usd": 0.40}
    return fake_run


def test_zero_confirmed_facts_lists_sources_not_claims(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    kept = [{"year": 1932, "claim": "stood tall", "verdict": "partly",
             "url": "https://a.example/x", "quote": "q"},
            {"year": 1986, "claim": "was painted", "verdict": "unverified",
             "url": "https://a.example/y", "quote": "q"}]
    failures = [
        {"url": "https://www.waymarking.com/x", "error": "HTTP 401 Unauthorized",
         "provider": "baseten"},
        {"url": "https://www.tripadvisor.com/y", "error": "HTTP 403 Forbidden",
         "provider": "baseten"},
        {"url": "https://aroundus.com/z",
         "error": "fetch exceeded its total time", "provider": "baseten"},
    ]
    run = _too_little_run(kept, failures, ["https://en.wikipedia.org/wiki/X"])
    monkeypatch.setattr(webfilm_module.cli, "run_job", run)
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: "out/q1-mill")
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "facts_only"}
        result = store.get_job("job-1")["result"]
        assert result["claims"] == []
        assert result["message"] == (
            "No film about Mill this time. We found 2 possible facts in "
            "4 sources, but couldn't confirm enough of them in sources we "
            "could open, so nothing was painted. Well-known landmarks "
            "with a Wikipedia page work best.")
        assert result["sources"] == [
            {"domain": "aroundus.com", "url": "https://aroundus.com/z",
             "outcome": "timed out"},
            {"domain": "en.wikipedia.org",
             "url": "https://en.wikipedia.org/wiki/X", "outcome": "read"},
            {"domain": "tripadvisor.com", "url": "https://www.tripadvisor.com/y",
             "outcome": "refused us"},
            {"domain": "waymarking.com", "url": "https://www.waymarking.com/x",
             "outcome": "asked for a login"},
        ]
    finally:
        models.configure_spending(None)


def test_source_outcomes_fall_back_to_could_not_open():
    from witness.webfilm import source_outcomes

    out = source_outcomes(
        [], [{"url": "https://gone.example/x", "error": "HTTP 404 Not Found",
              "provider": "baseten"}])
    assert out == [{"domain": "gone.example", "url": "https://gone.example/x",
                    "outcome": "couldn't open it"}]


def test_read_more_links_orders_visitor_language_first():
    import witness.webfilm as webfilm_module

    links = webfilm_module.read_more_links(
        "Q2487636",
        {"nl": "Watertoren (Roelofarendsveen)",
         "en": "Roelofarendsveen water tower"},
        "nl", "https://official.example/tower")
    assert [(link["label"], link["url"]) for link in links] == [
        ("Wikipedia (Dutch)",
         "https://nl.wikipedia.org/wiki/Watertoren_(Roelofarendsveen)"),
        ("Wikipedia (English)",
         "https://en.wikipedia.org/wiki/Roelofarendsveen_water_tower"),
        ("Official website", "https://official.example/tower"),
        ("Wikidata", "https://www.wikidata.org/wiki/Q2487636"),
    ]


def test_read_more_links_skips_bad_shapes():
    import witness.webfilm as webfilm_module

    assert webfilm_module.read_more_links(
        None, {}, "en", "http://plain.example/x") == []
    links = webfilm_module.read_more_links(
        "not-a-qid", {"en": "T"}, "en", None)
    assert [(link["label"], link["url"]) for link in links] == [
        ("Wikipedia (English)", "https://en.wikipedia.org/wiki/T")]
    links = webfilm_module.read_more_links(
        "Q1", {"en": "T"}, "en", "https://official.example/")
    assert [link["label"] for link in links] == [
        "Wikipedia (English)", "Official website", "Wikidata"]


def test_source_quotes_only_literal_wikipedia_sentences():
    import witness.webfilm as webfilm_module

    texts = {"https://en.wikipedia.org/wiki/Tower":
             "The tower was built in 1932. It is tall."}
    kept = [
        {"year": 1932, "claim": "built long ago", "verdict": "partly",
         "url": "https://en.wikipedia.org/wiki/Tower",
         "quote": "The tower was built in 1932."},
        {"year": 1900, "claim": "old", "verdict": "unsupported",
         "url": "https://en.wikipedia.org/wiki/Tower",
         "quote": "A sentence never fetched."},
    ]
    assert webfilm_module.source_quotes(kept, texts) == [
        {"text": "The tower was built in 1932.",
         "url": "https://en.wikipedia.org/wiki/Tower"}]


def test_source_quotes_skips_flagged_disputed_and_claim_text():
    import witness.webfilm as webfilm_module

    texts = {"https://en.wikipedia.org/wiki/T": "alpha beta gamma delta."}
    base = {"year": 1900, "claim": "model words",
            "url": "https://en.wikipedia.org/wiki/T", "quote": "alpha beta"}
    variants = [
        {**base, "war_politics_only": True},
        {**base, "refused_content": True},
        {**base, "note": "supporting sentence disputed, no clean source"},
        {**base, "support": [{"note": "sentence carries a dispute tag"}]},
        {**base, "quote": "model words"},
        {**base, "url": "https://official.example/page"},
        {**base, "url": "http://en.wikipedia.org/wiki/T"},
    ]
    for claim in variants:
        assert webfilm_module.source_quotes([claim], texts) == [], claim


def test_source_quotes_earliest_first_deduped_capped():
    import witness.webfilm as webfilm_module

    texts = {"https://en.wikipedia.org/wiki/T": "s1850 s1860 s1900 s2000"}
    kept = [{"year": year, "claim": f"model {year}",
             "url": "https://en.wikipedia.org/wiki/T", "quote": f"s{year}"}
            for year in (2000, 1850, 1900, 1860)]
    long = {"year": 1849, "claim": "model old",
            "url": "https://en.wikipedia.org/wiki/T",
            "quote": "s1849 " + "word " * 100}
    texts["https://en.wikipedia.org/wiki/T"] += " " + long["quote"]
    out = webfilm_module.source_quotes(
        kept + [long], texts, checked=["s1850"])
    assert [quote["text"] for quote in out] == [
        out[0]["text"], "s1860", "s1900"]
    assert len(out[0]["text"]) <= 300
    assert out[0]["text"].endswith("\u2026")
    assert out[0]["text"][-2] != " "
    assert len(out) == 3


def test_facts_payload_carries_subject_links_and_quotes():
    import witness.webfilm as webfilm_module

    links = [{"label": "Wikidata", "url": "https://www.wikidata.org/wiki/Q1"}]
    quotes = [{"text": "The tower stood.", "url": "https://en.wikipedia.org/wiki/T"}]
    payload = webfilm_module.facts_payload(
        [], ["https://en.wikipedia.org/wiki/T"], [], name="Mill",
        links=links, quotes=quotes)
    assert payload["subject"] == "Mill"
    assert payload["links"] == links
    assert payload["quotes"] == quotes


def test_public_claims_strips_leading_label_for_display():
    import witness.webfilm as webfilm_module

    kept = [
        {"year": 1560, "verdict": "supported",
         "claim": "repurposed (1560): After Scottish Reformation in 1560 "
                  "Catholic worship brought to an end",
         "url": "https://en.wikipedia.org/wiki/Rosslyn_Chapel",
         "quote": "After the Scottish Reformation in 1560, it was largely "
                  "abandoned."},
        {"year": 1592, "verdict": "supported",
         "claim": "damaged (1592): Chapel altars destroyed in 1592",
         "url": "https://en.wikipedia.org/wiki/Rosslyn_Chapel",
         "quote": "The chapel's altars were destroyed in 1592."},
        {"year": 1862, "verdict": "supported",
         "claim": "restored (1862): Restoration by David Bryce",
         "url": "https://en.wikipedia.org/wiki/Rosslyn_Chapel",
         "quote": "Restoration work was carried out in 1862 by David Bryce."},
        {"year": 2010, "verdict": "supported",
         "claim": "The chapel hosts concerts.",
         "url": "https://en.wikipedia.org/wiki/Rosslyn_Chapel",
         "quote": "The chapel hosts concerts."},
    ]
    out = webfilm_module.public_claims(kept)
    assert [claim["claim"] for claim in out] == [
        "After Scottish Reformation in 1560 Catholic worship brought to "
        "an end",
        "Chapel altars destroyed in 1592",
        "Restoration by David Bryce",
        "The chapel hosts concerts.",
    ]
    assert kept[0]["claim"].startswith("repurposed (1560):")


def test_public_claims_keeps_a_bare_prefix():
    import witness.webfilm as webfilm_module

    kept = [{"year": 1900, "verdict": "supported",
             "claim": "stood (1900):",
             "url": "https://en.wikipedia.org/wiki/Mill",
             "quote": "The mill stood in 1900."}]
    assert webfilm_module.public_claims(kept)[0]["claim"] == "stood (1900):"


def test_no_film_extras_carry_no_location():
    import witness.webfilm as webfilm_module

    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={"en": "Mill"})
    result = {"found": found,
              "kept": [{"year": 1850, "claim": "model words",
                        "url": "https://en.wikipedia.org/wiki/Mill",
                        "quote": "The mill stood in 1850."}],
              "texts": {"https://en.wikipedia.org/wiki/Mill":
                        "The mill stood in 1850. Lat 52.1, lon 4.3."}}
    links, quotes = webfilm_module.no_film_extras(result, knowledge=None)
    assert links and quotes

    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    seen = set(keys(list(links) + list(quotes)))
    assert seen <= {"label", "url", "text"}
    assert "52.1" not in str(links) + str(quotes)


def test_film_result_carries_no_extras(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    found = SimpleNamespace(name="Mill", kind="mill", qid="Q1",
                            articles={}, municipality=None)
    monkeypatch.setattr(
        webfilm_module.cli, "run_job",
        lambda *a, **k: {"confirmed": True, "identified": True,
                         "cached": False, "slug": "q1-mill", "found": found,
                         "order": ["en"], "kept": [], "timeline": [],
                         "chosen": [], "result": {"outcome": "full_film"},
                         "timings": {}, "failures": [], "read": [],
                         "comparison": None, "tokens": {}, "cost_usd": 0.0,
                         "texts": {}})
    monkeypatch.setattr(webfilm_module.cli, "report_and_save",
                        lambda *a, **k: None)
    monkeypatch.setattr(webfilm_module.cli, "cmd_captions",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_paint",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module.cli, "cmd_render",
                        lambda *a, **k: 0)
    monkeypatch.setattr(webfilm_module, "checked_facts", lambda *a: [])
    try:
        assert run_web_film(spec, store, authority=None) == {"status": "film"}
        result = store.get_job("job-1")["result"]
        assert "links" not in result
        assert "quotes" not in result
        assert "subject" not in result
    finally:
        models.configure_spending(None)


def test_web_job_skips_overpass(tmp_path, monkeypatch):
    import witness.webfilm as webfilm_module

    store, spec = _store(), _spec(tmp_path)
    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return {"confirmed": False, "identified": False, "cached": False,
                "error_kind": "no_location", "error": "no location",
                "identify_steps": {}}

    monkeypatch.setattr(webfilm_module.cli, "run_job", fake_run)
    try:
        run_web_film(spec, store, authority=None)
        assert seen.get("overpass") is False
    finally:
        models.configure_spending(None)
