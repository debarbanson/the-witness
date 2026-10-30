"""The Modal surface: separate-key store, ledger ops, worker wiring."""

import threading

import pytest

import modal_app
from modal_app import DictStore
from witness.webapp import MemoryStore


def _record(**overrides):
    record = {"vid": "v", "vkey": "k", "token": "t", "job_dir": "/jobs/job-x",
              "status": "started", "events": [], "started_at": 1000.0,
              "last_poll": 1000.0, "ended_at": None, "confirm": None,
              "decision": None, "cancel": False, "result": None}
    record.update(overrides)
    return record


def _op_sequence(store):
    store.create_job("j", _record())
    store.set_status("j", "working")
    store.append_event("j", {"event": "verifying"})
    store.set_confirm("j", {"name": "Mill", "kind": "mill"})
    store.touch("j")
    store.set_decision("j", True)
    store.append_event("j", {"event": "painting"})
    store.set_cancel("j")
    return store.get_job("j")


def test_dictstore_matches_the_memory_protocol():
    memory = MemoryStore(clock=lambda: 2000.0)
    over_dict = DictStore({})
    # DictStore has no clock; compare with ended/last_poll read back.
    got_memory = _op_sequence(memory)
    memory_tail = (got_memory["ended_at"], got_memory["last_poll"])
    got_dict = _op_sequence(over_dict)
    for key in ("vid", "vkey", "token", "job_dir", "status", "events",
                "started_at", "confirm", "decision", "cancel", "result"):
        assert got_dict[key] == got_memory[key], key
    assert got_dict["ended_at"] is not None
    assert got_dict["last_poll"] >= 1000.0
    assert memory_tail == (2000.0, 2000.0)


def test_worker_writes_never_lose_cancel_or_decision():
    store = DictStore({})
    store.create_job("j", _record())
    stop = threading.Event()

    def progress():
        for _ in range(200):
            store.append_event("j", {"event": "x"})
            store.set_status("j", "working")

    threads = [threading.Thread(target=progress) for _ in range(2)]
    for thread in threads:
        thread.start()
    store.set_decision("j", True)
    store.set_cancel("j")
    for thread in threads:
        thread.join()
    job = store.get_job("j")
    assert job["cancel"] is True
    assert job["decision"] is True
    assert job["ended_at"] is not None


def test_dictstore_job_ids_and_drop_cover_every_key():
    handle = {}
    store = DictStore(handle)
    store.create_job("j", _record())
    store.append_event("j", {"event": "x"})
    assert store.job_ids() == ["j"]
    store.drop_job("j")
    assert handle == {}
    assert store.job_ids() == []
    with pytest.raises(KeyError):
        store.get_job("j")


def test_dictstore_end_job_and_missing_job():
    store = DictStore({})
    store.create_job("j", _record())
    store.end_job("j", "failed", {"message": "no worker"})
    job = store.get_job("j")
    assert job["status"] == "failed"
    assert job["ended_at"] is not None
    with pytest.raises(KeyError):
        store.is_cancelled("missing")


def test_ledger_apply_admits_extra_and_counts_once():
    from modal_app import _apply_ledger_op

    data = {}
    for visitor, extra in (("vid-a", "ip:hash-a"), ("vid-b", "ip:hash-a")):
        data, answer = _apply_ledger_op(data, {"kind": "admit",
                                               "visitor": visitor,
                                               "extra": extra,
                                               "daily_films": 10,
                                               "visitor_films": 2})
        assert answer["ok"] is True
    data, answer = _apply_ledger_op(data, {"kind": "admit",
                                           "visitor": "vid-c",
                                           "extra": "ip:hash-a",
                                           "daily_films": 10,
                                           "visitor_films": 2})
    assert answer == {"ok": False, "error": "visitor quota"}
    assert data["films"] == 2
    assert data["visitors"]["ip:hash-a"] == 2


def test_ledger_apply_rejects_unknown_schema_and_ops():
    from modal_app import _apply_ledger_op

    _, answer = _apply_ledger_op({"schema": 999}, {"kind": "total"})
    assert answer == {"ok": False, "error": "accounting corrupt"}
    data, answer = _apply_ledger_op({}, {"kind": "total"})
    assert answer["ok"] is True
    assert data["schema"] == modal_app.LEDGER_SCHEMA
    _, answer = _apply_ledger_op({}, {"kind": "mint"})
    assert answer == {"ok": False, "error": "unknown op"}


def test_contact_is_required(monkeypatch):
    monkeypatch.delenv("WITNESS_CONTACT", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        modal_app._contact()
    assert "WITNESS_CONTACT" in str(excinfo.value)
    monkeypatch.setenv("WITNESS_CONTACT", "owner@example.com")
    assert modal_app._contact() == "owner@example.com"


def test_try_limits_match_the_page():
    from witness import webapp

    assert modal_app.TRY_DAILY_FILMS == webapp.MAX_FILMS_PER_DAY
    assert modal_app.TRY_VISITOR_FILMS == webapp.MAX_VISITOR_FILMS_PER_DAY


def test_watch_job_cancels_on_flag_and_stale_heartbeat():
    control = _control()
    store = MemoryStore(clock=lambda: 1000.0)
    store.create_job("j", _record(last_poll=1000.0))
    stop = threading.Event()
    modal_app._watch_job(store, "j", control, stop, poll_s=0.01,
                         heartbeat_s=3600, now=lambda: 1000.0)
    assert not stop.wait(0.2)
    assert not control.cancelled()
    stop.set()
    store.set_cancel("j")
    stop = threading.Event()
    modal_app._watch_job(store, "j", control, stop, poll_s=0.01,
                         heartbeat_s=3600, now=lambda: 1000.0)
    assert not stop.wait(0.5)
    stop.set()
    assert control.cancelled()

    control = _control()
    stale = MemoryStore(clock=lambda: 1000.0)
    stale.create_job("j", _record(last_poll=1000.0))
    stop = threading.Event()
    modal_app._watch_job(stale, "j", control, stop, poll_s=0.01,
                         heartbeat_s=120, now=lambda: 5000.0)
    assert not stop.wait(0.5)
    stop.set()
    assert control.cancelled()


def test_run_film_loads_the_spec_from_the_job_folder(tmp_path, monkeypatch):
    import json

    from witness import webfilm

    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    spec = {"job_id": "j", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "Test Town", "lat": None, "lon": None,
            "location": [52.1235, 4.5678]}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))
    seen = {}

    def fake_run(full_spec, job_store, authority):
        seen.update(full_spec)
        assert job_store is store
        full_spec["on_cancel"](_control())
        return {"status": "done"}

    class Volume:
        def reload(self):
            seen["reloaded"] = True

        def commit(self):
            seen["committed"] = True

    monkeypatch.setattr(modal_app, "jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store", lambda: store)
    monkeypatch.setattr(webfilm, "run_web_film", fake_run)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir)}) == {
        "status": "done"}
    assert seen["place"] == "Test Town"
    assert seen["location"] == [52.1235, 4.5678]
    assert seen["reloaded"] and seen["committed"]


def test_run_film_without_a_spec_ends_failed(tmp_path, monkeypatch):
    from witness import webfilm

    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))

    def boom(*args, **kwargs):
        raise AssertionError("runner must not start without a spec")

    class Volume:
        def reload(self):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(modal_app, "jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store", lambda: store)
    monkeypatch.setattr(webfilm, "run_web_film", boom)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir)}) == {
        "status": "failed"}
    job = store.get_job("j")
    assert job["status"] == "failed"
    assert job["ended_at"] is not None


def _control():
    from witness import models

    control = models.JobControl()
    control.cancelled = control._cancelled.is_set
    return control
