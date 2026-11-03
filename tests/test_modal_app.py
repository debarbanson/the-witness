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
    assert answer == {"ok": False, "error": "network quota"}
    assert data["films"] == 2
    assert data["visitors"]["ip:hash-a"]["n"] == 2


def test_ledger_counts_browser_and_network_separately():
    from modal_app import _apply_ledger_op

    data = {}
    for visitor in ("vid-a", "vid-b", "vid-c"):
        data, answer = _apply_ledger_op(data, {"kind": "admit",
                                               "visitor": visitor,
                                               "extra": "ip:office",
                                               "daily_films": 10,
                                               "visitor_films": 3,
                                               "network_films": 6,
                                               "now": 1000.0})
        assert answer["ok"] is True
    data, answer = _apply_ledger_op(data, {"kind": "admit",
                                           "visitor": "vid-a",
                                           "extra": "ip:office",
                                           "daily_films": 10,
                                           "visitor_films": 1,
                                           "network_films": 6,
                                           "now": 1000.0})
    assert answer == {"ok": False, "error": "visitor quota"}
    data, answer = _apply_ledger_op(data, {"kind": "admit",
                                           "visitor": "vid-z",
                                           "extra": "ip:office",
                                           "daily_films": 10,
                                           "visitor_films": 3,
                                           "network_films": 3,
                                           "now": 1000.0})
    assert answer == {"ok": False, "error": "network quota"}


def test_ledger_apply_rejects_unknown_schema_and_ops():
    from modal_app import _apply_ledger_op

    _, answer = _apply_ledger_op({"schema": 999}, {"kind": "total"})
    assert answer == {"ok": False, "error": "accounting corrupt"}
    data, answer = _apply_ledger_op({}, {"kind": "total"})
    assert answer["ok"] is True
    assert data["schema"] == modal_app.LEDGER_SCHEMA
    _, answer = _apply_ledger_op({}, {"kind": "mint"})
    assert answer == {"ok": False, "error": "unknown op"}


def test_ledger_ticket_reconciles_once():
    from modal_app import _apply_ledger_op

    data, answer = _apply_ledger_op(
        {}, {"kind": "reserve", "ticket_id": "t1", "ceiling_usd": 0.10,
             "cap_usd": 1.0})
    assert answer["ok"] is True
    data, answer = _apply_ledger_op(
        data, {"kind": "reconcile", "ticket_id": "t1",
               "ceiling_usd": 0.10, "actual_usd": 0.01})
    assert answer["ok"] is True
    assert answer["reserved_usd"] == 0.0
    _, answer = _apply_ledger_op(
        data, {"kind": "reconcile", "ticket_id": "t1",
               "ceiling_usd": 0.10, "actual_usd": 0.01})
    assert answer == {"ok": False, "error": "unknown ticket"}


def test_ledger_reset_clears_films_and_visitors_keeps_spend():
    from modal_app import _apply_ledger_op

    data, _ = _apply_ledger_op(
        {}, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
             "daily_films": 10, "visitor_films": 1})
    data, answer = _apply_ledger_op(
        data, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
               "daily_films": 10, "visitor_films": 1})
    assert answer == {"ok": False, "error": "visitor quota"}
    data, answer = _apply_ledger_op(data, {"kind": "reset"})
    assert answer["ok"] is True
    assert data["films"] == 0 and data["visitors"] == {}
    data, answer = _apply_ledger_op(
        data, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
               "daily_films": 10, "visitor_films": 1})
    assert answer["ok"] is True


def test_ledger_release_refunds_one_admission():
    from modal_app import _apply_ledger_op

    data, _ = _apply_ledger_op(
        {}, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
             "daily_films": 10, "visitor_films": 2, "now": 1000.0})
    data, answer = _apply_ledger_op(
        data, {"kind": "release", "visitor": "vid-a", "extra": "ip:h"})
    assert answer["ok"] is True
    assert data["films"] == 0
    assert data["visitors"]["vid-a"]["n"] == 0
    assert data["visitors"]["ip:h"]["n"] == 0
    data, answer = _apply_ledger_op(
        data, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
             "daily_films": 10, "visitor_films": 2, "now": 1000.0})
    assert answer["ok"] is True
    assert data["films"] == 1


def test_ledger_snapshot_reports_counts_not_keys():
    from modal_app import _apply_ledger_op

    data, _ = _apply_ledger_op(
        {}, {"kind": "admit", "visitor": "vid-a", "extra": "ip:h",
             "daily_films": 10, "visitor_films": 2})
    _, answer = _apply_ledger_op(data, {"kind": "snapshot"})
    assert answer["ok"] is True
    assert answer["films"] == 1 and answer["visitors"] == 2
    assert answer["calls"] == 0
    assert "vid-a" not in str(answer) and "ip:h" not in str(answer)


def test_modal_authority_reset_and_snapshot_call_ledger(monkeypatch):
    import modal_app

    ops = []
    auth = modal_app.ModalAuthority(cap_usd=1.0)
    def fake(op):
        ops.append(op)
        return {"ok": True, "films": 1, "visitors": 2, "calls": 0,
                "total_usd": 0.0, "reserved_usd": 0.0}

    monkeypatch.setattr(auth, "_call", fake)
    auth.reset_quotas()
    snap = auth.snapshot()
    assert [op["kind"] for op in ops] == ["reset", "snapshot"]
    assert snap["films"] == 1 and snap["visitors"] == 2


def test_modal_authority_tags_tickets_with_id_and_day(monkeypatch):
    import modal_app

    ops = []
    auth = modal_app.ModalAuthority(cap_usd=1.0)
    monkeypatch.setattr(
        auth, "_call", lambda op: ops.append(op) or {"ok": True})
    ticket = auth.reserve(0.10)
    auth.reconcile(ticket, 0.01)
    assert ops[0]["kind"] == "reserve"
    assert ops[0]["ticket_id"] == ticket.ticket_id == ops[1]["ticket_id"]
    assert ops[0]["day"] == ops[1]["day"]


def test_nominatim_slot_waits_out_the_second():
    from modal_app import _nominatim_wait

    assert _nominatim_wait(100.0, 100.5) == pytest.approx(0.5)
    assert _nominatim_wait(100.0, 101.5) == 0.0


def test_nominatim_slot_runs_single_flight():
    """One limiter shared across containers: the slot function
    serializes every Nominatim call (usage policy:
    https://operations.osmfoundation.org/policies/nominatim/)."""
    import re
    from pathlib import Path

    src = Path(modal_app.__file__).read_text()
    assert re.search(r"@app\.function\(image=image, max_containers=1\)\n"
                     r"def nominatim_slot", src)


def test_every_function_uses_the_app_image():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(modal_app.__file__).read_text())
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            if (isinstance(target, ast.Attribute)
                    and target.attr == "function"):
                assert isinstance(deco, ast.Call), node.name
                assert any(k.arg == "image" for k in deco.keywords), node.name


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
    assert modal_app.TRY_NETWORK_FILMS == webapp.MAX_NETWORK_FILMS_PER_DAY


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
            "location": [12.3457, 65.4321]}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))
    seen = {}

    def fake_run(full_spec, job_store, authority, nominatim_pace=None,
                 commit=None):
        seen.update(full_spec)
        assert job_store is store
        assert callable(nominatim_pace)
        full_spec["on_cancel"](_control())
        return {"status": "done"}

    class Volume:
        def reload(self):
            seen["reloaded"] = True

        def commit(self):
            seen["committed"] = True

    monkeypatch.setattr(modal_app, "jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store",
                            lambda backend="staging": store)
    monkeypatch.setattr(webfilm, "run_web_film", fake_run)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir)}) == {
        "status": "done"}
    assert seen["place"] == "Test Town"
    assert seen["location"] == [12.3457, 65.4321]
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
    monkeypatch.setattr(modal_app, "_worker_store",
                            lambda backend="staging": store)
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


def test_modal_image_builds_from_the_lockfile():
    from pathlib import Path

    root = Path(modal_app.__file__).parent
    src = (root / "modal_app.py").read_text()
    assert 'pip_install_from_requirements("requirements-lock.txt")' in src
    assert ".pip_install([" not in src
    lock = (root / "requirements-lock.txt").read_text()
    for package in ("fastapi==", "pillow==", "openai==", "meta-sam-parser==",
                    "python-multipart==", "modal=="):
        assert package in lock, package


def test_install_instructions_name_the_lockfile():
    from pathlib import Path

    readme = (Path(modal_app.__file__).parent / "README.md").read_text()
    assert "requirements-lock.txt" in readme
    assert "playwright install chromium" in readme
    assert "ffmpeg" in readme


def test_ip_secret_is_required(monkeypatch):
    monkeypatch.delenv("WITNESS_IP_SECRET", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        modal_app._ip_secret()
    assert "WITNESS_IP_SECRET" in str(excinfo.value)
    good = "ab12" * 16
    monkeypatch.setenv("WITNESS_IP_SECRET", good)
    assert modal_app._ip_secret() == good


def test_run_film_scrubs_and_commits_before_starting_work(tmp_path,
                                                          monkeypatch):
    import json

    from witness import webfilm

    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    spec = {"job_id": "j", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "Test Town", "lat": None, "lon": None,
            "location": [12.3457, 65.4321]}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))
    seen = []

    def fake_run(full_spec, job_store, authority, nominatim_pace=None,
                 commit=None):
        on_disk = json.loads((job_dir / "spec.json").read_text())
        assert "place" not in on_disk and "location" not in on_disk
        assert seen == ["committed"]
        full_spec["on_cancel"](_control())
        return {"status": "done"}

    class Volume:
        def reload(self):
            pass

        def commit(self):
            seen.append("committed")

    monkeypatch.setattr(modal_app, "jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store",
                            lambda backend="staging": store)
    monkeypatch.setattr(webfilm, "run_web_film", fake_run)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir)}) == {
        "status": "done"}


def test_spawn_returns_the_worker_handle():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(modal_app.__file__).read_text())
    web = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == "web")
    spawn = next(n for n in ast.walk(web) if isinstance(n, ast.FunctionDef)
                 and n.name == "spawn")
    returns = [n for n in ast.walk(spawn) if isinstance(n, ast.Return)
               and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Attribute)
               and n.value.func.attr == "spawn"]
    assert len(returns) == 1


def _judge_fn():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(modal_app.__file__).read_text())
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "judge")


def test_judge_has_no_proxy_auth_and_staging_does():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(modal_app.__file__).read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("web",
                                                               "judge"):
            for deco in node.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                if (isinstance(target, ast.Attribute)
                        and target.attr == "asgi_app"):
                    if isinstance(deco, ast.Call):
                        flags = {k.arg: ast.literal_eval(k.value)
                                 for k in deco.keywords if k.arg}
                    else:
                        flags = {}
                    found[node.name] = flags.get("requires_proxy_auth",
                                                 False)
    assert found == {"web": True, "judge": False}


def test_judge_wiring_pins_safety_flags():
    import ast

    judge = _judge_fn()
    calls = [n for n in ast.walk(judge) if isinstance(n, ast.Call)]
    deps = next(n for n in calls
                if isinstance(n.func, ast.Name) and n.func.id == "WebDeps")
    flags = {}
    for key in deps.keywords:
        if isinstance(key.value, ast.Constant):
            flags[key.arg] = key.value.value
        elif isinstance(key.value, ast.Name):
            flags[key.arg] = key.value.id
        elif isinstance(key.value, ast.Call):
            flags[key.arg] = ast.dump(key.value.func)
    assert flags["noindex"] is True
    assert flags["debug_reset"] is False
    assert flags["try_enabled"] == "_try_enabled"
    assert "jobs_root" in flags
    authority = next(n for n in calls
                     if isinstance(n.func, ast.Name)
                     and n.func.id == "ModalAuthority")
    auth_flags = {k.arg: k.value for k in authority.keywords}
    assert isinstance(auth_flags["cap_usd"], ast.Call)
    assert auth_flags["cap_usd"].func.id == "_judge_cap"
    assert ast.literal_eval(auth_flags["backend"]) == "judge"


def test_both_apps_render_the_secret_contact():
    import ast
    from pathlib import Path

    src = Path(modal_app.__file__).read_text()
    assert "owner@example.com" not in src
    assert "example.com" not in src
    tree = ast.parse(src)
    for name in ("web", "judge"):
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == name)
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        deps = next(n for n in calls
                    if isinstance(n.func, ast.Name)
                    and n.func.id == "WebDeps")
        contact = next(k.value for k in deps.keywords if k.arg == "contact")
        assert isinstance(contact, ast.Call)
        assert contact.func.id == "_contact"


def test_film_limits_default_and_refuse_bad_values(monkeypatch):
    for name in ("WITNESS_DAILY_FILMS", "WITNESS_VISITOR_FILMS",
                 "WITNESS_NETWORK_FILMS"):
        monkeypatch.delenv(name, raising=False)
    assert modal_app._daily_films() == 10
    assert modal_app._visitor_films() == 2
    assert modal_app._network_films() == 2
    for bad in ("", "  ", "0", "-3", "2.5", "many"):
        monkeypatch.setenv("WITNESS_VISITOR_FILMS", bad)
        with pytest.raises(RuntimeError):
            modal_app._visitor_films()
    monkeypatch.setenv("WITNESS_VISITOR_FILMS", "3")
    monkeypatch.setenv("WITNESS_NETWORK_FILMS", "6")
    monkeypatch.setenv("WITNESS_DAILY_FILMS", "25")
    assert modal_app._visitor_films() == 3
    assert modal_app._network_films() == 6
    assert modal_app._daily_films() == 25


def test_judge_cap_requires_a_positive_number(monkeypatch):
    monkeypatch.delenv("WITNESS_JUDGE_CAP_USD", raising=False)
    with pytest.raises(RuntimeError):
        modal_app._judge_cap()
    for bad in ("abc", "-1", "0", "nan"):
        monkeypatch.setenv("WITNESS_JUDGE_CAP_USD", bad)
        with pytest.raises(RuntimeError):
            modal_app._judge_cap()
    monkeypatch.setenv("WITNESS_JUDGE_CAP_USD", "12.5")
    assert modal_app._judge_cap() == 12.5


def test_try_switch_flips_the_flag(monkeypatch):
    flag = {}
    monkeypatch.setattr(modal_app, "try_flag_dict", flag)
    assert modal_app._try_enabled() is True
    modal_app.try_switch.local(False)
    assert flag == {"enabled": False}
    assert modal_app._try_enabled() is False
    modal_app.try_switch.local(True)
    assert modal_app._try_enabled() is True


def test_try_enabled_fails_closed_when_unreadable(monkeypatch):
    class Broken:
        def get(self, key, default=None):
            raise OSError("synthetic dict outage")

    monkeypatch.setattr(modal_app, "try_flag_dict", Broken())
    assert modal_app._try_enabled() is False


def test_volume_examples_lists_ready_films(tmp_path):
    ready = tmp_path / "de-adriaan"
    ready.mkdir()
    (ready / "film.html").write_text("synthetic")
    found = modal_app._volume_examples(tmp_path)
    assert found == [{"slug": "de-adriaan",
                      "name": "De Adriaan, Haarlem"}]
    assert modal_app._volume_examples(tmp_path / "empty") == []


def test_production_ledger_is_isolated(monkeypatch):
    staging, judge = {}, {}
    monkeypatch.setattr(modal_app, "ledger_dict", staging)
    monkeypatch.setattr(modal_app, "judge_ledger_dict", judge)
    answer = modal_app.ledger_op.local(
        {"kind": "admit", "visitor": "v", "daily_films": 10,
         "visitor_films": 2, "now": 1000.0, "backend": "judge"})
    assert answer["ok"] is True
    assert staging == {}
    assert len(judge) == 1
    answer = modal_app.ledger_op.local({"kind": "total",
                                        "backend": "nope"})
    assert answer == {"ok": False, "error": "unknown backend"}


def test_modal_authority_carries_its_backend(monkeypatch):
    ops = []

    class LedgerFn:
        def remote(self, op):
            ops.append(op)
            return {"ok": True, "total_usd": 0.0, "reserved_usd": 0.0}

    monkeypatch.setattr(modal_app, "ledger_op", LedgerFn())
    modal_app.ModalAuthority(cap_usd=1.0, backend="judge").admit("v")
    assert ops[0]["backend"] == "judge"
    modal_app.ModalAuthority(cap_usd=1.0).admit("v")
    assert ops[1]["backend"] == "staging"


def test_judge_refuses_test_flags(monkeypatch):
    monkeypatch.delenv("WITNESS_FAKE_PROVIDER", raising=False)
    monkeypatch.delenv("WITNESS_ABUSE_RESET", raising=False)
    modal_app._check_judge_flags()
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    with pytest.raises(RuntimeError):
        modal_app._check_judge_flags()
    monkeypatch.delenv("WITNESS_FAKE_PROVIDER", raising=False)
    monkeypatch.setenv("WITNESS_ABUSE_RESET", "1")
    with pytest.raises(RuntimeError):
        modal_app._check_judge_flags()


def test_judge_calls_the_flag_check():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(modal_app.__file__).read_text())
    judge = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "judge")
    calls = [n for n in ast.walk(judge)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "_check_judge_flags"]
    assert len(calls) == 1


def test_run_film_refuses_fake_for_judge(tmp_path, monkeypatch):
    import json

    from witness import webfilm

    monkeypatch.setenv("WITNESS_JUDGE_CAP_USD", "12.5")
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    spec = {"job_id": "j", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "", "lat": None, "lon": None, "location": None}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))

    def boom(*args, **kwargs):
        raise AssertionError("fake judge film must not start")

    class Volume:
        def reload(self):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(modal_app, "judge_jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store",
                        lambda backend="staging": store)
    monkeypatch.setattr(webfilm, "run_web_film", boom)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir),
                                     "backend": "judge"}) == {
        "status": "failed"}
    assert store.get_job("j")["status"] == "failed"


def test_run_film_allows_fake_for_staging(tmp_path, monkeypatch):
    import json

    from witness import webfilm

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    spec = {"job_id": "j", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "", "lat": None, "lon": None, "location": None}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))

    def fake_run(full_spec, job_store, authority, nominatim_pace=None,
                 commit=None):
        full_spec["on_cancel"](_control())
        return {"status": "done"}

    class Volume:
        def reload(self):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(modal_app, "jobs_volume", Volume())
    monkeypatch.setattr(modal_app, "_worker_store",
                        lambda backend="staging": store)
    monkeypatch.setattr(webfilm, "run_web_film", fake_run)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir),
                                     "backend": "staging"}) == {
        "status": "done"}


def test_run_film_routes_by_backend(tmp_path, monkeypatch):
    import json

    from witness import webfilm

    monkeypatch.setenv("WITNESS_JUDGE_CAP_USD", "12.5")

    job_dir = tmp_path / "job-x"
    job_dir.mkdir()
    spec = {"job_id": "j", "token": "t", "vid": "v",
            "job_dir": str(job_dir), "photo": str(job_dir / "today.jpg"),
            "place": "", "lat": None, "lon": None, "location": None}
    (job_dir / "spec.json").write_text(json.dumps(spec))
    (job_dir / "today.jpg").write_bytes(b"x")
    store = MemoryStore()
    store.create_job("j", _record(job_dir=str(job_dir)))
    seen = []

    def fake_run(full_spec, job_store, authority, nominatim_pace=None,
                 commit=None):
        full_spec["on_cancel"](_control())
        return {"status": "done"}

    def recorder(name):
        class Volume:
            def reload(self):
                seen.append((name, "reload"))

            def commit(self):
                seen.append((name, "commit"))

        return Volume()

    backends = []

    def worker_store(backend="staging"):
        backends.append(backend)
        return store

    monkeypatch.setattr(modal_app, "jobs_volume", recorder("staging"))
    monkeypatch.setattr(modal_app, "judge_jobs_volume",
                        recorder("judge"))
    monkeypatch.setattr(modal_app, "_worker_store", worker_store)
    monkeypatch.setattr(webfilm, "run_web_film", fake_run)
    assert modal_app.run_film.local({"job_id": "j",
                                     "job_dir": str(job_dir),
                                     "backend": "judge"}) == {
        "status": "done"}
    assert backends == ["judge"]
    assert seen == [("judge", "reload"), ("judge", "commit"),
                    ("judge", "commit")]
    store.create_job("k", _record(job_dir=str(job_dir)))
    assert modal_app.run_film.local({"job_id": "k",
                                     "job_dir": str(job_dir),
                                     "backend": "nope"}) == {
        "status": "failed"}
    assert store.get_job("k")["status"] == "failed"


def test_worker_store_creates_missing_state(monkeypatch):
    seen = {}

    def fake_from_name(name, **kwargs):
        seen[name] = kwargs
        return {}

    monkeypatch.setattr(modal_app.modal.Dict, "from_name",
                        staticmethod(fake_from_name))
    modal_app._worker_store("staging")
    modal_app._worker_store("judge")
    assert seen["witness-store"].get("create_if_missing") is True
    assert seen["witness-judge-store"].get("create_if_missing") is True
