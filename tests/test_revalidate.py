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
