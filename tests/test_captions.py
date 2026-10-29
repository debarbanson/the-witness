"""Adult line-2 sentences: one written sentence per scene from its own
verified claim, each claim used once, or a plain no-fact line."""

import pytest

from witness import captions


def claim(year, url="https://a.example/x", verdict="supported", **extra):
    base = {"year": year, "url": url, "verdict": verdict,
            "claim": f"something happened in {year}",
            "quote": f"It happened in {year}."}
    base.update(extra)
    return base


def scene(year):
    return {"from_year": year,
            "state": {"condition": "standing", "degree": "total",
                      "scope": "whole", "description": ""}}


def test_assign_claims_matches_own_year_only():
    assigned = captions.assign_claims(
        [scene(1779), scene(1865)],
        [claim(1865), claim(1779), claim(1925)])
    assert assigned[1779]["year"] == 1779
    assert assigned[1865]["year"] == 1865
    assert 1925 not in assigned


def test_assign_claims_skips_unverified_and_non_object_years():
    assigned = captions.assign_claims(
        [scene(1779), {"from_year": "today", "state": {}}],
        [claim(1779, verdict="unsupported")])
    assert assigned == {}


def test_assign_claims_prefers_most_informative_claim():
    thin = claim(2019, claim="structure relocation in 2019")
    rich = claim(2019, claim="moved: On 22 October 2019 the 23-metre, "
                            "720-tonne lighthouse was moved 70 m inland")
    assert captions.assign_claims([scene(2019)], [thin, rich])[2019] is rich
    assert captions.assign_claims([scene(2019)], [rich, thin])[2019] is rich


def test_assign_claims_uses_each_claim_once():
    spanning = claim(1899, from_year=1899, to_year=1968)
    assigned = captions.assign_claims(
        [scene(1920), scene(1930)], [spanning])
    assert assigned[1920] is spanning
    assert 1930 not in assigned


def test_assign_claims_skips_age_range_scenes():
    aged = scene(1026)
    aged["date_label"] = "about 800 to 1,200 years old"
    assigned = captions.assign_claims([aged], [claim(1026)])
    assert assigned == {}


def test_assign_claims_accepts_a_span_covering_the_scene():
    spanning = claim(1899, from_year=1899, to_year=1968)
    assigned = captions.assign_claims([scene(1920)], [spanning])
    assert assigned[1920] is spanning
    assert captions.assign_claims([scene(1970)], [spanning]) == {}


def test_write_sentence_keeps_supported_rewrite():
    out = captions.write_sentence(
        rewrite_call=lambda detail, quote, year, plain: "My sails turned for the miller.",
        support_call=lambda sentence, quote: "supported",
        claim=claim(1865), year=1865)
    assert out == {"sentence": "My sails turned for the miller.",
                   "verified": True, "attempts": 1}


def test_write_sentence_keeps_partly_verified_rewrite():
    out = captions.write_sentence(
        rewrite_call=lambda detail, quote, year, plain: "I burnt down that evening.",
        support_call=lambda sentence, quote: "partly",
        claim=claim(1932), year=1932)
    assert out == {"sentence": "I burnt down that evening.",
                   "verified": True, "attempts": 1}


def test_write_sentence_retries_shorter_once_then_fails():
    calls = []

    def rewrite(detail, quote, year, plain):
        calls.append(plain)
        return "Much too long " * 20 if not plain else "Still much too long " * 20

    out = captions.write_sentence(
        rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported",
        claim=claim(1865), year=1865)
    assert out == {"sentence": None, "verified": False, "attempts": 2}
    assert calls == [False, True]


def test_write_sentence_rejects_borrowed_years_and_cutting():
    seen = []

    def rewrite(detail, quote, year, plain):
        return seen.pop(0)

    seen[:] = ["I was saved in 1925, they say.",
               "I was saved in 1925, really."]
    out = captions.write_sentence(
        rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported",
        claim=claim(1920), year=1920)
    assert out["verified"] is False
    seen[:] = ["Something happened…", "Other things…"]
    out = captions.write_sentence(
        rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported",
        claim=claim(1920), year=1920)
    assert out["verified"] is False


def test_sentence_ok_checks_person_year_and_length():
    assert captions.sentence_ok("I ground corn for the town.", 1865)
    assert captions.sentence_ok("My sails turned all day.", 1865)
    assert not captions.sentence_ok("The mill ground corn.", 1865)
    assert not captions.sentence_ok("I saw the mill burn.", 1865)
    assert not captions.sentence_ok("We put the first pole down.", 1865)
    assert not captions.sentence_ok("Our sails turned all day.", 1865)
    assert not captions.sentence_ok("I was saved in 1925.", 1920)
    assert not captions.sentence_ok("I stood here…", 1865)
    assert not captions.sentence_ok("", 1865)
    assert not captions.sentence_ok("I " + "x" * 200, 1865)
    assert captions.sentence_ok("I stood here in 1865.", 1865)


def test_sentence_prompt_forbids_years_and_cutting():
    prompt = captions.sentence_prompt("converted to a flour mill",
                                    "The mill was converted in 1865.", 1865)
    assert "first-person" in prompt
    assert "You are the object itself" in prompt
    assert "the claim's main event" in prompt
    assert "if the source gives an age, include it" in prompt
    assert "my sails, my buildings" in prompt
    assert "1865" in prompt
    assert "only what the source" in prompt
    assert "The mill was converted in 1865." in prompt


def test_fallback_line_has_no_fact_and_differs_per_scene():
    first = captions.fallback_line(scene(1026))
    second = captions.fallback_line(scene(1790))
    assert first and second and first != second
    assert "…" not in first
    assert captions.sentence_ok(first, 1026)
    assert captions.sentence_ok(second, 1790)
    with pytest.raises(KeyError):
        captions.fallback_line({"from_year": "today", "state": {}})
