"""Evidence pages: every quote on the page is the literal bound quote."""

import html
import json
import re
from pathlib import Path

from witness.render import evidence


def _slug(tmp_path):
    root = tmp_path / "q1-mill"
    (root / "film").mkdir(parents=True)
    research = {
        "object": {"name": "Test Mill"},
        "claims": [
            {"year": 1850, "event": "built", "verdict": "supported",
             "claim": "built in 1850: The mill was built in 1850.",
             "quote": "The mill was built in 1850.",
             "url": "https://a.example/mill", "votes": 2, "rounds": [],
             "note": "", "support": [
                 {"url": "https://a.example/mill", "supports": True,
                  "quote": "The mill was built in 1850."}]},
            {"year": 1900, "event": "burnt", "verdict": "unsupported",
             "claim": "burnt in 1900: The mill burnt down in 1900.",
             "quote": "", "url": "", "votes": 2, "rounds": [],
             "note": "no supporting source", "support": [
                 {"url": "https://a.example/mill", "supports": False,
                  "quote": ""}]},
        ],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing",
                       "description": "newly built with four sails"},
             "caption_sentence": {
                 "text": "I was opened.",
                 "claim_year": 1850,
                 "claim_url": "https://a.example/mill",
                 "child": {"text": "I was opened."},
                 "evidence": {
                     "claim": "built in 1850",
                     "url": "https://a.example/mill",
                     "quote": "The mill was built in 1850."}}},
        ],
    }
    (root / "research.json").write_text(json.dumps(research))
    manifest = {"audience": "adult", "season": "spring", "eras": [
        {"year": 1850, "verdict": "matches", "attempts": 2,
         "caption": "I was opened.",
         "file": "eras_parallel_strict/1850.png",
         "binding": "ab12cd34ef56ab12cd34ef56ab12cd34"
                    "ef56ab12cd34ef56ab12cd34ef56ab12"},
    ]}
    (root / "paint_parallel_strict.json").write_text(json.dumps(manifest))
    film = {"object": "Test Mill", "audience": "adult",
            "scenes": [
                {"year": 1850, "date_label": "1850",
                 "image": "era_1850.webp",
                 "caption": ["1850", "I was opened."],
                 "site": "Example",
                 "caption_claim": {"year": 1850,
                                  "url": "https://a.example/mill"}}]}
    (root / "film" / "film.json").write_text(json.dumps(film))
    (root / "film" / "era_1850.webp").write_bytes(b"synthetic-era")
    return root


def _quotes(page):
    return [html.unescape(match) for match in
            re.findall(r'<blockquote class="quote"[^>]*>(.*?)</blockquote>',
                       page, re.S)]


def test_every_quote_is_the_literal_bound_quote(tmp_path):
    root = _slug(tmp_path)
    page = evidence.build_page(root)
    quotes = _quotes(page)
    assert quotes, "the page must show its quotes"
    research = json.loads((root / "research.json").read_text())
    bound = {scene["caption_sentence"]["evidence"]["quote"]
             for scene in research["scenes"]}
    for quote in quotes:
        assert quote in bound, quote


def test_refused_claim_appears_verbatim(tmp_path):
    root = _slug(tmp_path)
    page = evidence.build_page(root, refused_year=1900)
    assert "burnt in 1900: The mill burnt down in 1900." in page
    assert "unsupported" in page
    assert "no supporting source" in page


def test_refused_defaults_to_the_first_unaccepted_claim(tmp_path):
    root = _slug(tmp_path)
    page = evidence.build_page(root)
    assert "burnt in 1900" in page


def test_steps_name_models_and_recorded_verdicts(tmp_path):
    root = _slug(tmp_path)
    page = evidence.build_page(root)
    lowered = page.lower()
    assert "muse spark" in lowered
    assert "muse image" in lowered
    assert "baseten" in lowered
    assert "supported" in lowered
    assert "matches" in lowered
    assert "2 attempt(s)" in page or "attempts" in lowered
    assert "I was opened." in page
    assert "era_1850.webp" in page
    assert "newly built with four sails" in page
    assert "<h2>1850: I was opened.</h2>" in page
    assert " — " not in page
