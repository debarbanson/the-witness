"""Spot the difference: grounded vision differences, tap to reveal. No live calls."""

import pytest

from witness import spot


def scene(year, description):
    return {
        "from_year": year, "date_label": str(year),
        "state": {"condition": "standing", "degree": "total",
                  "scope": "whole", "description": description},
    }


def claim(year, verdict="supported"):
    return {"year": year, "verdict": verdict, "claim": f"change in {year}",
            "quote": f"It changed in {year}.",
            "url": "https://a.example/x"}


CHANGES = [
    "1779: The mill stands whole with four sails.",
    "1932: The mill burnt, only the base left.",
    "2002: The mill rebuilt with new sails.",
    "2020: The mill repainted white.",
]


def test_verified_changes_cover_only_the_era_through_today():
    scenes = [scene(1779, "The mill stands whole with four sails."),
              scene(1865, "A guessed extension."),
              scene(1900, ""),
              scene(1932, "The mill burnt, only the base left.")]
    claims = [claim(1779), claim(1865, verdict="unsupported"), claim(1900),
              claim(1932)]
    assert spot.verified_changes(scenes, claims, 1779) == [
        "1779: The mill stands whole with four sails.",
        "1932: The mill burnt, only the base left."]
    assert spot.verified_changes(scenes, claims, 1932) == [
        "1932: The mill burnt, only the base left."]


def test_pick_year_is_the_earliest_painted_change():
    scenes = [scene(1779, "The mill stands whole."),
              scene(1932, "The mill burnt."),
              scene(2002, "The mill rebuilt.")]
    claims = [claim(1779), claim(1932), claim(2002)]
    assert spot.pick_year(scenes, claims, {"1932", "2002"}) == 1932
    assert spot.pick_year(scenes, claims, {"2002"}) == 2002
    assert spot.pick_year(scenes, claims, set()) is None
    assert spot.pick_year([scene(1900, "")], [claim(1900)], {"1900"}) is None


def test_pick_year_prefers_the_era_that_looks_least_like_today():
    scenes = [scene(1779, "The mill stands whole."),
              scene(1932, "The mill burnt."),
              scene(2002, "The mill rebuilt.")]
    scenes[1]["state"]["condition"] = "ruin"
    claims = [claim(1779), claim(1932), claim(2002)]
    assert spot.pick_year(scenes, claims, {"1779", "1932", "2002"}) == 1932
    scenes[1]["state"]["condition"] = "standing"
    assert spot.pick_year(scenes, claims, {"1779", "1932", "2002"}) == 1779


def test_prompt_lists_every_change_and_forbids_invention():
    prompt = spot.spot_prompt(CHANGES)
    for line in CHANGES:
        assert line in prompt
    assert "only" in prompt
    assert "3 to 5" in prompt
    assert "look different" in prompt
    assert "looks the same" in prompt


def test_choose_keeps_grounded_differences():
    visions = [
        {"text": "The sails are gone.", "change": CHANGES[1]},
        {"text": "The paint is fresh.", "change": CHANGES[3]},
        {"text": "Four sails again.", "change": CHANGES[2]},
    ]
    got = spot.choose(lambda era, photo, prompt: visions, b"e", b"p", CHANGES)
    # The child sees the verified line itself, never the vision wording.
    assert got == [{"change": CHANGES[1]}, {"change": CHANGES[3]},
                   {"change": CHANGES[2]}]


def test_choose_dedupes_by_change_not_by_text():
    visions = [
        {"text": "The sails are gone.", "change": CHANGES[1]},
        {"text": "A dragon on the roof.", "change": "1932: A dragon landed."},
        {"text": "The base is charred.", "change": CHANGES[1]},
        {"text": "Fresh paint.", "change": CHANGES[3]},
        {"text": "Whole mill.", "change": CHANGES[0]},
        {"text": "One too many.", "change": CHANGES[2]},
    ]
    got = spot.choose(lambda era, photo, prompt: visions, b"e", b"p", CHANGES)
    assert got == [{"change": CHANGES[1]}, {"change": CHANGES[3]},
                   {"change": CHANGES[0]}, {"change": CHANGES[2]}]


def test_choose_counts_three_items_on_one_change_as_one():
    visions = [
        {"text": "The sails are gone.", "change": CHANGES[1]},
        {"text": "The base is charred.", "change": CHANGES[1]},
        {"text": "Everything burnt.", "change": CHANGES[1]},
        {"text": "Fresh paint.", "change": CHANGES[3]},
    ]
    assert spot.choose(lambda e, p, pr: visions, b"e", b"p", CHANGES) is None


def test_choose_refuses_fewer_than_three_or_unparseable():
    two = [{"text": "One.", "change": CHANGES[0]},
           {"text": "Two.", "change": CHANGES[1]}]
    assert spot.choose(lambda e, p, pr: two, b"e", b"p", CHANGES) is None
    assert spot.choose(lambda e, p, pr: None, b"e", b"p", CHANGES) is None
    assert spot.choose(lambda e, p, pr: "not a list", b"e", b"p", CHANGES) is None
    assert spot.choose(lambda e, p, pr: (_ for _ in ()).throw(AssertionError),
                       b"e", b"p", CHANGES[:2]) is None


def test_check_game_revalidates_at_render():
    scenes = [scene(1779, "The mill stands whole with four sails."),
              scene(1932, "The mill burnt, only the base left."),
              scene(2002, "The mill rebuilt with new sails."),
              scene(2020, "The mill repainted white.")]
    claims = [claim(1779), claim(1932), claim(2002), claim(2020)]
    good = {"year": 1779, "era": "era_1779.png",
            "differences": [
                {"change": CHANGES[0]},
                {"change": CHANGES[2]},
                {"change": CHANGES[3]}]}
    assert spot.check_game(good, scenes, claims, {"1779"}) is True
    bad_year = dict(good, year=1865)
    assert spot.check_game(bad_year, scenes, claims, {"1779"}) is False
    invented = {"year": 1779, "era": "era_1779.png",
                "differences": [
                    {"change": CHANGES[0]},
                    {"change": "1932: A dragon landed."},
                    {"change": CHANGES[3]}]}
    assert spot.check_game(invented, scenes, claims, {"1779"}) is False
    short = dict(good, differences=good["differences"][:2])
    assert spot.check_game(short, scenes, claims, {"1779"}) is False
    one_change = {"year": 1779, "era": "era_1779.png",
                  "differences": [{"change": CHANGES[0]}] * 3}
    assert spot.check_game(one_change, scenes, claims, {"1779"}) is False
    earlier = {"year": 2002, "era": "era_2002.png",
               "differences": [{"change": CHANGES[0]},
                               {"change": CHANGES[2]},
                               {"change": CHANGES[3]}]}
    assert spot.check_game(earlier, scenes, claims, {"2002"}) is False
