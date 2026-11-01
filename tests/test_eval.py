"""Open-weights support eval: shape of the case sets. No live calls."""

import importlib.util
import json
import re
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent / "eval"


def _cases():
    return json.loads((EVAL / "support_cases.json").read_text())


def _hard_cases():
    return json.loads((EVAL / "hard_cases.json").read_text())


def _runner():
    path = EVAL / "run_support_eval.py"
    spec = importlib.util.spec_from_file_location("run_support_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_hard_case_set_shape():
    cases = _hard_cases()
    assert len(cases) >= 20
    ids = [case["id"] for case in cases]
    assert len(set(ids)) == len(ids)
    support_ids = {case["id"] for case in _cases()}
    assert not (set(ids) & support_ids)
    groups = {case["group"] for case in cases}
    assert len(groups) >= 4
    assert {"true", "negation", "wrong_object", "date_shift",
            "partial"} & groups == set()
    expected = {case["expected"] for case in cases}
    assert expected == {"accept", "reject"}
    for case in cases:
        assert case["claim"] and case["quote"] and case["url"]
        assert case["url"].startswith("https://")


def test_hard_quotes_come_from_kept_research():
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
    for case in _hard_cases():
        assert case["quote"] in kept
        assert kept[case["quote"]] == case["url"]


def test_runner_loads_named_sets():
    import pytest

    runner = _runner()
    assert runner.load_cases("support") == _cases()
    assert runner.load_cases("hard") == _hard_cases()
    with pytest.raises(KeyError):
        runner.load_cases("no_such_set")


def test_runner_results_path_names_set():
    runner = _runner()
    support = runner.results_path("support")
    hard = runner.results_path("hard")
    assert re.fullmatch(r"support_results_\d{4}-\d{2}-\d{2}\.json",
                        support.name)
    assert re.fullmatch(r"hard_results_\d{4}-\d{2}-\d{2}\.json", hard.name)
    assert support.parent == hard.parent == EVAL


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
