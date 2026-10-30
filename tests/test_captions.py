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


def test_partly_claim_matches_no_scene():
    assert captions.claim_matches(claim(1932, verdict="partly"), 1932) is False
    assert captions.claim_matches(claim(1932), 1932) is True


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
        rewrite_call=lambda detail, quote, year, plain, stamp="": "My sails turned for the miller.",
        support_call=lambda sentence, quote: "supported",
        claim=claim(1865), year=1865)
    assert out == {"sentence": "My sails turned for the miller.",
                   "verified": True, "attempts": 1}


def test_write_sentence_keeps_partly_verified_rewrite():
    out = captions.write_sentence(
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I burnt down that evening.",
        support_call=lambda sentence, quote: "partly",
        claim=claim(1932), year=1932)
    assert out == {"sentence": "I burnt down that evening.",
                   "verified": True, "attempts": 1}


def test_write_sentence_retries_shorter_once_then_fails():
    calls = []

    def rewrite(detail, quote, year, plain, stamp=""):
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

    def rewrite(detail, quote, year, plain, stamp=""):
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
    assert captions.sentence_ok("I ground corn for the town.")
    assert captions.sentence_ok("My sails turned all day.")
    assert not captions.sentence_ok("The mill ground corn.")
    assert not captions.sentence_ok("I saw the mill burn.")
    assert not captions.sentence_ok("We put the first pole down.")
    assert not captions.sentence_ok("Our sails turned all day.")
    assert not captions.sentence_ok("I was saved in 1925.")
    assert not captions.sentence_ok("I stood here…")
    assert not captions.sentence_ok("")
    assert not captions.sentence_ok("I " + "x" * 200)
    assert not captions.sentence_ok("I stood here in 1865.")
    assert captions.sentence_ok("I was reopened 70 years after the fire.")


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


def test_unmatched_scene_gets_no_sentence():
    assigned = captions.assign_claims([scene(1865)], [claim(1779)])
    assert assigned == {}


def test_other_texts_collects_scene_evidence_beyond_the_main_quote():
    main = claim(1932, quote="The brigade could not prevent it.",
                 support=[{"url": "u1", "supports": True,
                           "quote": "The brigade could not prevent it."},
                          {"url": "u1", "supports": True,
                           "quote": "The cause was never established."}])
    other = claim(1932, claim="burnt on the evening of April 23, 1932",
                  quote="On the evening of April 23, 1932 it burnt down.",
                  support=[{"url": "u2", "supports": True,
                            "quote": "On the evening of April 23, 1932 it burnt down."},
                           {"url": "u3", "supports": False, "quote": "Rumour."}])
    unrelated = claim(1865, claim="converted to steam",
                      support=[{"url": "u4", "supports": True,
                                "quote": "Converted."}])
    texts = captions.other_texts(main, [main, other, unrelated], 1932)
    assert "burnt on the evening of April 23, 1932" in texts
    assert "On the evening of April 23, 1932 it burnt down." in texts
    assert "The cause was never established." in texts
    assert "The brigade could not prevent it." not in texts
    assert "something happened in 1932" not in texts
    assert "Rumour." not in texts
    assert "Converted." not in texts


def test_sentence_prompt_leaves_out_disputed_details():
    prompt = captions.sentence_prompt("detail words.", "Quote words.", 1932)
    assert "disagree" in prompt
    assert "leave that detail out" in prompt


def test_sentence_prompt_names_the_stamp_and_asks_for_natural_numbers():
    prompt = captions.sentence_prompt("d", "q", 2019, stamp="22 October 2019")
    assert "22 October 2019" in prompt
    assert "naturally" in prompt
    assert "22 October 2019" not in captions.sentence_prompt("d", "q", 2019)


def test_sentence_ok_rejects_any_date():
    assert not captions.sentence_ok("I burnt down on 23 April 1932.")
    assert not captions.sentence_ok("I burnt down in 1932.")
    assert captions.sentence_ok("I burnt down.")
    assert captions.sentence_ok("I stood here quietly.")
    assert captions.sentence_ok("I stood 23 metres from the cliff.")


def test_write_sentence_forwards_the_stamp():
    seen = {}

    def rewrite(detail, quote, year, plain, stamp=""):
        seen["stamp"] = stamp
        return "I was moved."

    out = captions.write_sentence(
        rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported",
        claim=claim(2019), year=2019, stamp="22 October 2019")
    assert out["verified"] is True
    assert seen["stamp"] == "22 October 2019"


def test_write_sentence_checks_the_combined_evidence():
    seen = {}

    def rewrite(detail, quote, year, plain, stamp=""):
        seen["source"] = quote
        return "I burnt down."

    def support(sentence, quote):
        return "supported" if "23 April 1932" in quote else "unsupported"

    out = captions.write_sentence(
        rewrite_call=rewrite, support_call=support,
        claim=claim(1932, quote="The brigade could not prevent it."), year=1932,
        other_texts=["On the evening of 23 April 1932 it burnt down."])
    assert out["verified"] is True
    assert "On the evening of 23 April 1932 it burnt down." in seen["source"]


def test_write_sentence_retries_without_the_contested_detail():
    seen = []

    def rewrite(detail, quote, year, plain, stamp=""):
        seen.append(plain)
        if not plain:
            return "I burnt down in the evening."
        return "I burnt down."

    def support(sentence, quote):
        if "evening" in sentence:
            return "unsupported"
        return "supported"

    out = captions.write_sentence(
        rewrite_call=rewrite, support_call=support,
        claim=claim(1932, quote="The brigade could not prevent it."), year=1932,
        other_texts=["On Saturday afternoon, April 23rd, 1932 it burnt."])
    assert out == {"sentence": "I burnt down.",
                   "verified": True, "attempts": 2}
    assert seen == [False, True]
