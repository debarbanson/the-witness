"""The example revalidation script: passes clear stale failure notes."""

import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
          / "revalidate_examples.py")


def _load():
    spec = importlib.util.spec_from_file_location("revalidate_examples",
                                                  SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scene():
    return {"from_year": 1932, "date_label": "23 April 1932",
            "state": {"condition": "destroyed", "degree": "total",
                      "scope": "whole", "description": "Burnt shell."},
            "caption_sentence": {
                "text": "I burnt down.", "claim_year": 1932,
                "evidence": {"claim": "Burnt in 1932.",
                             "url": "https://a.example/fire",
                             "quote": "The mill burnt down on 23 April 1932."}}}


def test_pass_clears_the_failure_note_and_refreshes_the_caption():
    module = _load()
    entry = {"year": 1932, "verdict": "matches",
             "caption": "I burnt down completely.",
             "note": "revalidation: caption=True paint=False"}
    module.refresh_entry(entry, _scene(), "Mill", "adult",
                         cap_ok=True, paint_ok=True, paint_note="fine")
    assert entry["verdict"] == "matches"
    assert "binding" in entry
    assert "note" not in entry
    assert entry["caption"] != "I burnt down completely."
    assert "burnt down" in entry["caption"].lower()


def test_fail_drops_the_binding_and_records_the_verdicts():
    module = _load()
    entry = {"year": 1932, "verdict": "matches", "binding": {"old": True},
             "caption": "I burnt down.", "note": "revalidation: stale"}
    module.refresh_entry(entry, _scene(), "Mill", "adult",
                         cap_ok=True, paint_ok=False, paint_note="roof wrong")
    assert entry["verdict"] == "dropped"
    assert "binding" not in entry
    assert entry["note"] == "revalidation: caption=True paint=False"


def test_record_lists_the_required_fields():
    module = _load()
    record = module.era_record(
        "q1-mill", 1932, "adult", b"image-bytes", _scene(),
        [{"ok": True, "note": "sentence verified"}],
        [{"ok": True, "note": "MATCHES whole mill."}],
        seconds=12.5, cost_usd=0.011)
    assert record["slug"] == "q1-mill"
    assert record["year"] == 1932
    assert len(record["sha256"]) == 64
    assert "burnt down" in record["caption"].lower()
    assert record["state"]["condition"] == "destroyed"
    assert "23 April 1932" in record["quote"]
    assert record["url"] == "https://a.example/fire"
    assert record["caption_verdicts"] == [{"ok": True,
                                           "note": "sentence verified"}]
    assert record["paint_verdicts"] == [{"ok": True,
                                         "note": "MATCHES whole mill."}]
    assert record["seconds"] == 12.5
    assert record["cost_usd"] == 0.011
    dumped = __import__("json").dumps(record)
    assert "52." not in dumped and "4." not in dumped.split("cost")[0]


def test_failed_rows_keep_a_final_disposition():
    import json

    record = Path(__file__).resolve().parent.parent / (
        "eval/example_revalidation_2026-11-04.json")
    saved = json.loads(record.read_text())
    assert saved["reviewed_sha"]
    assert "two passes out of three" in saved["rule"]
    for row in saved["records"]:
        paint = [v["ok"] for v in row["paint_verdicts"]]
        cap_ok = row["caption_verdicts"][-1]["ok"]
        if cap_ok and (paint[0] or sum(paint) >= 2):
            continue
        assert row.get("disposition"), (row["slug"], row["year"],
                                        row["audience"])


def test_paint_tries_run_all_three_after_a_failure():
    module = _load()
    planned = iter([(False, "first failure"), (True, "second pass"),
                    (False, "third failure")])
    verdicts = module.run_paint_tries(lambda: next(planned))
    assert [v["ok"] for v in verdicts] == [False, True, False]


def test_paint_tries_stop_at_a_first_pass():
    module = _load()
    calls = []
    verdicts = module.run_paint_tries(
        lambda: (calls.append(1), (True, "matches"))[1])
    assert [v["ok"] for v in verdicts] == [True]
    assert len(calls) == 1


def test_paint_kept_needs_first_pass_or_two_of_three():
    module = _load()
    assert module.paint_kept([{"ok": True, "note": ""}]) is True
    assert module.paint_kept([{"ok": False, "note": ""},
                              {"ok": True, "note": ""},
                              {"ok": True, "note": ""}]) is True
    assert module.paint_kept([{"ok": False, "note": ""},
                              {"ok": True, "note": ""},
                              {"ok": False, "note": ""}]) is False
    assert module.paint_kept([{"ok": False, "note": ""},
                              {"ok": False, "note": ""},
                              {"ok": False, "note": ""}]) is False


def test_third_check_appends_and_recomputes(tmp_path, monkeypatch):
    import hashlib
    import json

    module = _load()
    root = tmp_path / "out"
    slug_dir = root / "q1-mill"
    (slug_dir / "eras_parallel_strict").mkdir(parents=True)
    image = b"painted-bytes"
    (slug_dir / "eras_parallel_strict" / "1779.png").write_bytes(image)
    (slug_dir / "research.json").write_text(json.dumps(
        {"object": {"name": "Mill"},
         "scenes": [{"from_year": 1779, "date_label": "1779",
                     "state": {"condition": "standing"}}],
         "claims": []}))
    (slug_dir / "paint_parallel_strict.json").write_text(json.dumps(
        {"eras": [{"year": 1779, "verdict": "matches",
                   "file": "eras_parallel_strict/1779.png"}]}))
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(
        {"date": "2026-11-04",
         "records": [{"slug": "q1-mill", "year": 1779,
                      "audience": "adult",
                      "sha256": hashlib.sha256(image).hexdigest(),
                      "caption_verdicts": [{"ok": True, "note": "fine"}],
                      "paint_verdicts": [{"ok": False, "note": "roof"},
                                         {"ok": True, "note": "ok"}]}]}))
    monkeypatch.setattr(module, "check_painting",
                        lambda *a, **k: (True, "third pass"))
    code = module.main(["revalidate_examples.py", "--third",
                        "q1-mill,1779,adult"],
                       root=root, record_path=record_path)
    assert code == 0
    saved = json.loads(record_path.read_text())
    assert saved["reviewed_sha"] == module.REVIEWED_SHA
    assert "two passes out of three" in saved["rule"]
    row = saved["records"][0]
    assert [v["ok"] for v in row["paint_verdicts"]] == [False, True, True]


def test_third_check_refuses_a_moved_image(tmp_path, monkeypatch):
    import json

    module = _load()
    root = tmp_path / "out"
    slug_dir = root / "q1-mill"
    (slug_dir / "eras_parallel_strict").mkdir(parents=True)
    (slug_dir / "eras_parallel_strict" / "1779.png").write_bytes(b"new bytes")
    (slug_dir / "research.json").write_text(json.dumps(
        {"object": {"name": "Mill"}, "scenes": [], "claims": []}))
    (slug_dir / "paint_parallel_strict.json").write_text(json.dumps(
        {"eras": [{"year": 1779, "verdict": "matches",
                   "file": "eras_parallel_strict/1779.png"}]}))
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(
        {"date": "2026-11-04",
         "records": [{"slug": "q1-mill", "year": 1779,
                      "audience": "adult", "sha256": "0" * 64,
                      "caption_verdicts": [{"ok": True, "note": "fine"}],
                      "paint_verdicts": [{"ok": False, "note": "roof"},
                                         {"ok": True, "note": "ok"}]}]}))
    seen = []
    monkeypatch.setattr(module, "check_painting",
                        lambda *a, **k: (seen.append(1), (True, ""))[1])
    code = module.main(["revalidate_examples.py", "--third",
                        "q1-mill,1779,adult"],
                       root=root, record_path=record_path)
    assert code == 2
    assert seen == []
    saved = json.loads(record_path.read_text())
    assert len(saved["records"][0]["paint_verdicts"]) == 2


def test_sync_writes_manifests_from_the_record_without_checks(
        tmp_path, monkeypatch):
    import json

    module = _load()
    root = tmp_path / "out"
    slug_dir = root / "q1-mill"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(
        {"object": {"name": "Mill"},
         "scenes": [_scene()],
         "claims": []}))
    manifest_path = slug_dir / "paint_parallel_strict.json"
    manifest_path.write_text(json.dumps(
        {"eras": [{"year": 1932, "verdict": "matches",
                   "caption": "I burnt down completely.",
                   "note": "revalidation: caption=True paint=False"}]}))
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(
        {"date": "2026-11-04",
         "records": [{"slug": "q1-mill", "year": 1932,
                      "audience": "adult", "sha256": "0" * 64,
                      "caption_verdicts": [{"ok": True, "note": "fine"}],
                      "paint_verdicts": [{"ok": True, "note": "fine"}]}]}))

    def no_check(*args, **kwargs):
        raise AssertionError("sync must not check")

    monkeypatch.setattr(module, "check_caption", no_check)
    monkeypatch.setattr(module, "check_painting", no_check)
    code = module.main(["revalidate_examples.py", "--sync"],
                       root=root, record_path=record_path)
    assert code == 0
    entry = json.loads(manifest_path.read_text())["eras"][0]
    assert entry["verdict"] == "matches"
    assert "note" not in entry
    assert "binding" in entry
