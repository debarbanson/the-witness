"""Block 1: a state is what you would see in front of the object.

Condition from a fixed list, degree, scope, and a free sourced
description of the visible change. One meaning question decides state
vs caption: does this change what the object physically looks like?
No blocklists of event names or properties. No live calls.
"""

import pytest

from witness import states


def test_looks_incomplete_flags_doubt():
    assert states.looks_incomplete("restored", "Promise fell into oblivion.") is True
    assert states.looks_incomplete("rebuilt", "Rebuild planned; first pole in.") is False
    assert states.looks_incomplete("built", "Built in 1932.") is False


def test_fixed_conditions():
    assert states.CONDITIONS == (
        "under_construction",
        "standing",
        "damaged",
        "burnt",
        "ruin",
        "rebuilt",
        "moved",
        "demolished",
    )
    assert states.DEGREES == ("partial", "total")
    assert states.SCOPES == ("whole", "part")


def classify(event, detail="", visible_change="", previous=None):
    found = states.classify(event, detail, visible_change, previous)
    assert found is not None
    assert found["condition"] in states.CONDITIONS
    assert found["degree"] in states.DEGREES
    assert found["scope"] in states.SCOPES
    return found


def test_construction_and_completion():
    assert classify("construction", "Built 1869 to 1883.")["condition"] == "under_construction"
    assert classify("significant event", "start of construction")["condition"] == "under_construction"
    assert classify("built", "Built in 1673.")["condition"] == "standing"
    assert classify("significant event", "end of construction")["condition"] == "standing"
    assert classify("built", "Main structural work completed end March 1889.")["condition"] == "standing"


def test_total_destruction_is_ruin():
    found = classify("burnt", "Completely burnt down on 23 April 1932.")
    assert (found["condition"], found["degree"], found["scope"]) == ("ruin", "total", "whole")
    assert classify("damaged", "Washed away in a flood from a typhoon.")["condition"] == "ruin"
    assert classify("significant event", "conflagration")["condition"] == "ruin"


def test_survived_fire_is_partly_burnt():
    biosphere = classify("burnt", "Severely damaged in a fire; the steel frame survived.")
    assert (biosphere["condition"], biosphere["degree"]) == ("burnt", "partial")
    oak = classify("burnt", "Significant damage from a fire, tree survived.")
    assert (oak["condition"], oak["degree"]) == ("burnt", "partial")


def test_damage_and_lightning():
    found = classify("damaged", "Twelve suspender cables snapped.")
    assert (found["condition"], found["degree"]) == ("damaged", "partial")
    assert classify("significant event", "lightning strike")["condition"] == "damaged"


def test_rebuilt_and_restored():
    assert classify("rebuilt", "Rebuilt to its original design.")["condition"] == "rebuilt"
    assert classify("rebuilt", "Rebuild started; first pole in the ground.")["condition"] == "under_construction"
    assert classify("restored", "Thorough cleaning and restoration.")["condition"] == "standing"
    assert classify("significant event", "renovation")["condition"] == "standing"


def test_moved_and_demolished():
    assert classify("moved", "Moved 70 m inland.")["condition"] == "moved"
    assert classify("significant event", "structure relocation")["condition"] == "moved"
    assert classify("demolished", "Pulled down in 1960.")["condition"] == "demolished"


def test_part_scope_never_sets_a_whole_state():
    assert states.scope_of("demolished", "Small outbuildings removed.") == "part"
    assert states.classify("demolished", "Small outbuildings removed.") is None
    assert states.classify("demolished", "Small buildings were later removed.") is None
    assert states.scope_of("demolished", "Pulled down in 1960.") == "whole"
    assert states.scope_of("extended", "A pair of wings was completed.") == "whole"
    assert states.classify("restored", "Fences were installed around the tree.") is None
    assert states.classify("repurposed", "Renamed; the main entrance was moved.") is None


def test_part_damage_keeps_part_state():
    found = classify("damaged", "Twelve suspender cables snapped.")
    assert (found["condition"], found["scope"]) == ("damaged", "part")


def test_event_word_beats_context_words_in_detail():
    widened = classify(
        "extended",
        "Widened to three lanes, restoration finished with reconstructed promenade.")
    assert widened["condition"] == "standing"
    palace = classify(
        "built",
        "First mosque built when the king converted and had his palace pulled down.")
    assert palace["condition"] == "standing"
    girders = classify(
        "restored",
        "Girders were restored; reconstruction work took place in three phases.")
    assert girders["condition"] == "standing"


def test_detail_destruction_beats_vague_damage_event():
    found = classify("damaged", "Washed away again in a flood from a typhoon.")
    assert found["condition"] == "ruin"


def test_fire_protection_is_not_fire():
    found = classify("restored", "Limbs covered in lead and treated with fire-retardant paint.")
    assert found["condition"] == "standing"


def test_temporal_beginning_is_not_work_start():
    found = classify("restored", "Branches supported by scaffolding beginning in the 1970s.")
    assert found["condition"] == "standing"


def test_rebuild_after_standing_is_facelift_after_ruin_is_rebuild():
    assert classify("rebuilt", "Decorations removed and new lighting added.",
                    previous="standing")["condition"] == "standing"
    assert classify("rebuilt", "Museum opened inside the frame.",
                    previous="burnt")["condition"] == "rebuilt"
    assert classify("rebuilt", "Rebuilt to its original design.",
                    previous="rebuilt")["condition"] == "rebuilt"


def test_built_event_with_construction_start_is_ongoing():
    found = classify("built", "Construction began in 1899; start bouw 1899.")
    assert found["condition"] == "under_construction"
    found = classify("built", "Construction started 1887; built 1887-1889.")
    assert found["condition"] == "under_construction"
    found = classify("built", "Construction project led by Fuller began in December 1965.")
    assert found["condition"] == "under_construction"


def test_ordered_work_is_not_started_work():
    assert classify("rebuilt", "Rebuilding of the mosque arranged in 1906.",
                    previous="standing")["condition"] == "standing"
    assert classify("restored", "Improvements were commissioned in 2009.")["condition"] == "standing"


def test_completed_rebuild_after_standing_is_still_rebuild():
    assert classify("rebuilt", "Rebuilding completed in 1907; current structure dates from 1907.",
                    previous="standing")["condition"] == "rebuilt"


def test_near_destruction_is_damage():
    found = classify("damaged", "Mosque damaged, near-destroyed by invaders.")
    assert (found["condition"], found["degree"]) == ("damaged", "partial")
    found = classify("burnt", "The roof almost burnt down.")
    assert (found["condition"], found["degree"]) == ("burnt", "partial")


def test_foundation_stone_is_ceremony_not_state():
    assert states.classify("built", "Foundation stone laid 4 April 1922.") is None
    assert states.classify("built", "Completed 1931; foundation stone laid 1922.")["condition"] == "standing"


def test_surviving_frame_downgrades_destroyed_to_burnt():
    found = classify("burnt", "Acrylic membrane destroyed by fire; steel frame remained.")
    assert (found["condition"], found["degree"]) == ("burnt", "partial")
    assert classify("damaged", "Washed away after remaining intact for 276 years.")["condition"] == "ruin"


def test_visible_alterations_keep_standing_with_description():
    assert classify("extended", "Widened to three lanes.", "widened to three lanes") == {
        "condition": "standing", "degree": "total", "scope": "whole",
        "description": "widened to three lanes",
    }
    assert classify("repainted", "Repainted white.", "repainted white")["description"] == "repainted white"


def test_unseen_cases_sails_pollard_raised_statue():
    sails = classify("restored", "The sails were replaced with new ones.", "sails replaced")
    assert (sails["condition"], sails["description"]) == ("standing", "sails replaced")
    pollard = classify("restored", "The tree was pollarded back to the trunk.", "pollarded")
    assert (pollard["condition"], pollard["description"]) == ("standing", "pollarded")
    raised = classify("extended", "A new storey raised the tower by 6 m.", "height raised")
    assert (raised["condition"], raised["description"]) == ("standing", "height raised")
    statue = classify("moved", "The statue was moved to the museum square.", "moved to museum square")
    assert (statue["condition"], statue["scope"]) == ("moved", "whole")


@pytest.mark.parametrize(
    "event,detail",
    [
        ("image", "Tour Eiffel Wikimedia Commons.jpg"),
        ("architect", "Peter Hall"),
        ("heritage designation", "National Historic Landmark"),
        ("designated", "Declared a National Monument in 1987."),
        ("repurposed", "Converted into a museum."),
        ("renamed", "Renamed after Major Hayman Rooke."),
        ("demolition-planned", "Slated for dismantling in 1909."),
        ("moved-proposed", "Secret agreement to dismantle and relocate."),
        ("restored", "Tried to restore it; that failed for lack of funds."),
        ("restored", "Took an obligation to rebuild; the promise fell into oblivion."),
        ("inception", "First mentioned in the chronicle."),
    ],
)
def test_non_visible_history_is_caption_only(event, detail):
    assert states.classify(event, detail) is None


@pytest.mark.parametrize(
    "time,precision,expected",
    [
        ("+1932-00-00T00:00:00Z", 9, "in 1932"),
        ("+1887-01-28T00:00:00Z", 11, "in 1887"),
        ("+1960-00-00T00:00:00Z", 8, "in the 1960s"),
        ("+1000-00-00T00:00:00Z", 7, "in the 11th century"),
        ("+1700-00-00T00:00:00Z", 7, "in the 18th century"),
        ("+1000-00-00T00:00:00Z", 6, "around 1000"),
    ],
)
def test_format_wikidate_uses_precision(time, precision, expected):
    assert states.format_wikidate(time, precision) == expected


def test_rebuild_after_standing_with_destruction_stated_is_rebuild():
    found = classify("rebuilt", "The bridge was destroyed by a flood and was "
                     "rebuilt in 1674 with improvements.", previous="standing")
    assert found["condition"] == "rebuilt"


def test_first_lighting_is_operational_completion():
    found = classify("built", "Construction began in 1899; light first turned "
                     "on 27 December 1900.")
    assert found["condition"] == "standing"
    found = classify("built", "Tower finished; first lit on 1 May 1901.")
    assert found["condition"] == "standing"


def test_last_lighting_is_not_completion():
    found = classify("built", "Construction began in 1899; light lit for last "
                     "time in 1968.")
    assert found["condition"] == "under_construction"


def test_ancillary_buildings_are_parts():
    assert states.scope_of("demolished", "Demolished the barracks.") == "part"
    assert states.classify("demolished", "Demolished the barracks.") is None
    assert states.classify("demolished", "Pulled down in 1960.") is not None


@pytest.mark.parametrize(
    "condition,from_year,to_year,claim,next_condition,flagged",
    [
        ("standing", 1932, 1986, "Built in 1932.", "standing", False),
        ("rebuilt", 2002, None, "Reopened in 2002.", None, False),
        ("under_construction", 1959, 1973, "Built in four stages.", "standing", False),
        ("under_construction", 1899, 1953, "Construction began in 1899.",
         "demolished", True),
        ("ruin", 1932, 1999, "Burnt down in 1932.", "under_construction", False),
        ("ruin", 1674, 1950, "Bridge re-erected in 1674.", "ruin", True),
        ("burnt", 1976, 1990, "Covering burned away.", "standing", False),
        ("burnt", 1900, 1960, "Burnt in 1900.", "standing", True),
        ("damaged", 1901, 1981, "Cables broken.", "damaged", True),
        ("ruin", 1900, 1980, "Stood in ruins for 80 years.", "standing", False),
    ],
)
def test_implausible_spans_flagged(condition, from_year, to_year, claim,
                                  next_condition, flagged):
    found = states.check_span(condition, from_year, to_year, claim, next_condition)
    assert (found is not None) == flagged


@pytest.mark.parametrize(
    "date_text,year,expected",
    [
        ("", 1908, "1908"),
        ("in 1908", 1908, "1908"),
        ("in the 1960s", 1965, "the 1960s"),
        ("between 800 and 1,200 years old", 1026, "about 800 to 1,200 years old"),
        ("between 400 and 500 years old", 1576, "about 400 to 500 years old"),
        ("in the 11th century", 1026, "the 11th century"),
    ],
)
def test_date_label_prefers_ranges_over_sort_year(date_text, year, expected):
    assert states.date_label(date_text, year) == expected
