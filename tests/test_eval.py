"""Open-weights support eval: shape of the case set. No live calls."""

import json
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent / "eval"


def _cases():
    return json.loads((EVAL / "support_cases.json").read_text())


def test_case_set_covers_all_groups():
    cases = _cases()
    assert len(cases) >= 40
    groups = {case["group"] for case in cases}
    assert {"true", "negation", "wrong_object", "date_shift",
            "partial"} <= groups
    for case in cases:
        assert case["expected"] in ("accept", "reject")
        assert case["claim"] and case["quote"] and case["url"]
        assert case["url"].startswith("https://")


def test_true_cases_come_from_kept_research():
    import pytest

    kept = {}
    for slug in ("q2763574-de-adriaan", "q388443-major-oak",
                 "q2206180-rubjerg-knude-fyr"):
        path = (EVAL.parent / "out" / slug / "research.json")
        if not path.exists():
            continue
        for claim in json.loads(path.read_text()).get("claims", []):
            if claim.get("verdict") == "supported":
                kept[claim["quote"]] = claim["url"]
    if not kept:
        pytest.skip("kept research (git-ignored) needed to ground the set")
    for case in _cases():
        if case["group"] == "true":
            assert case["quote"] in kept
            assert kept[case["quote"]] == case["url"]
