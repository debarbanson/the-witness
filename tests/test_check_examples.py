"""The example freshness check: live film payloads equal the local ones."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_examples.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_examples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _film(caption="I burnt down.", year=1932):
    return {"sibling_page": "child/film.html",
            "today_line": "Photographed in 2012.",
            "scenes": [{"year": year, "caption": ["23 April 1932", caption]}]}


def test_compare_accepts_equal_payloads():
    module = _load()
    assert module.compare(_film(), _film()) == []


def test_compare_names_the_changed_scene():
    module = _load()
    problems = module.compare(_film(), _film("I burnt down completely."))
    assert problems
    assert any("1932" in problem for problem in problems)


def _layout(root: Path, live_caption="I burnt down.", evidence=True):
    local = root / "local" / "out" / "q2763574-de-adriaan" / "film"
    (local / "child").mkdir(parents=True)
    payload = _film()
    (local / "film.json").write_text(json.dumps(payload))
    (local / "child" / "film.json").write_text(json.dumps(payload))
    live = root / "live" / "examples" / "de-adriaan"
    (live / "child").mkdir(parents=True)
    changed = _film(live_caption)
    (live / "film.json").write_text(json.dumps(changed))
    (live / "child" / "film.json").write_text(json.dumps(changed))
    if evidence:
        (live / "evidence.html").write_text("<html></html>")
    others = {"de-adriaan": "out/q2763574-de-adriaan",
              "major-oak": "out/q388443-major-oak",
              "rubjerg-knude": "out/q2206180-rubjerg-knude-fyr"}
    for slug, local_dir in others.items():
        if slug == "de-adriaan":
            continue
        place = root / "local" / local_dir / "film"
        (place / "child").mkdir(parents=True)
        (place / "film.json").write_text(json.dumps(payload))
        (place / "child" / "film.json").write_text(json.dumps(payload))
        side = root / "live" / "examples" / slug
        (side / "child").mkdir(parents=True)
        (side / "film.json").write_text(json.dumps(payload))
        (side / "child" / "film.json").write_text(json.dumps(payload))
        (side / "evidence.html").write_text("<html></html>")
    return root / "local", (root / "live").as_uri()


def test_check_passes_when_live_matches_local(tmp_path):
    module = _load()
    root, base = _layout(tmp_path)
    assert module.check(base, root) == []


def test_check_reports_a_stale_live_caption(tmp_path):
    module = _load()
    root, base = _layout(tmp_path, live_caption="I burnt down completely.")
    problems = module.check(base, root)
    assert any("de-adriaan" in problem and "1932" in problem
               for problem in problems), problems


def test_check_reports_a_missing_evidence_page(tmp_path):
    module = _load()
    root, base = _layout(tmp_path, evidence=False)
    problems = module.check(base, root)
    assert any("de-adriaan" in problem and "evidence" in problem
               for problem in problems), problems
