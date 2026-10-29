"""Step 2: Wikidata facts first, then grounded web research. No live calls."""

import json
from pathlib import Path

import pytest

from witness import research

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def fake_get(script):
    calls = []

    def get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(script.pop(0))

    get.calls = calls
    return get


def test_fetch_facts_resolves_labels_and_references():
    recorded = fixture("wb_facts_q2487636.json")
    get = fake_get(
        [
            {"entities": {recorded["qid"]: {"labels": {"nl": {"value": recorded["label"]}}, "claims": recorded["claims"]}}},
            fixture("wb_labels_q2487636.json"),
        ]
    )
    facts = research.fetch_facts("Q2487636", get=get)
    assert facts["label"] == "watertoren Roelofarendsveen"
    assert facts["commons_category"] is None
    assert facts["image"] == "Roelofarendsveen watertoren.jpg"
    architect = next(f for f in facts["facts"] if f["property"] == "P84")
    assert architect["value"] == {"qid": "Q1975202", "label": "Hendrik Sangster"}
    assert "P143" in architect["references"][0]
    designation = next(f for f in facts["facts"] if f["property"] == "P1435")
    assert designation["references"] == []


def test_lifespan_question_reads_local_languages_first():
    question = research.lifespan_question(
        "Test Tower", "Test Town", {"nl": "Testtoren", "en": "Test Tower"},
        read_langs=["nl", "en"],
    )
    assert question.index("nl.wikipedia.org/wiki/Testtoren") < question.index("en.wikipedia")
    assert "Do not narrate" in question


def test_lifespan_question_reading_order_is_configurable():
    question = research.lifespan_question(
        "Test Tower", "Test Town", {"nl": "Testtoren", "en": "Test Tower"},
        read_langs=["en", "nl"],
    )
    assert question.index("en.wikipedia.org/wiki/Test_Tower") < question.index("nl.wikipedia")


def test_read_langs_local_first_then_user_then_english():
    assert research.read_langs("nl", "en") == ["nl", "en"]
    assert research.read_langs("ca", "en") == ["fr", "en"]
    assert research.read_langs("dk", "fr") == ["da", "fr", "en"]
    assert research.read_langs("se", "en") == ["sv", "en"]
    assert research.read_langs("es", "en") == ["es", "ca", "en"]
    assert research.read_langs("it", "en") == ["it", "en"]
    assert research.read_langs("pt", "en") == ["pt", "en"]
    assert research.read_langs(None, "en") == ["en"]
    assert research.read_langs("xx", "en") == ["en"]


def test_fetch_facts_requests_local_languages_first():
    recorded = fixture("wb_facts_q2487636.json")
    get = fake_get(
        [
            {"entities": {recorded["qid"]: {"labels": {}, "claims": recorded["claims"]}}},
            fixture("wb_labels_q2487636.json"),
        ]
    )
    research.fetch_facts("Q2487636", get=get, country_code="jp", lang="en")
    assert get.calls[0]["params"]["languages"] == "ja|en"


def test_fetch_facts_labels_in_user_language_with_english_fallback():
    recorded = fixture("wb_facts_q2487636.json")

    def fetch(lang):
        get = fake_get(
            [
                {"entities": {recorded["qid"]: {"labels": {"nl": {"value": recorded["label"]}}, "claims": recorded["claims"]}}},
                fixture("wb_labels_q2487636.json"),
            ]
        )
        return research.fetch_facts("Q2487636", get=get, lang=lang)

    designation_en = next(f for f in fetch("en")["facts"] if f["property"] == "P1435")
    assert designation_en["value"]["label"] == "municipal monument"
    designation_nl = next(f for f in fetch("nl")["facts"] if f["property"] == "P1435")
    assert designation_nl["value"]["label"] == "gemeentelijk monument"
    architect = next(f for f in fetch("en")["facts"] if f["property"] == "P84")
    assert architect["references"][0]["P143"][0]["label"] == "Nederlandstalige Wikipedia"


def test_ask_lifespan_reads_last_message_only():
    answer = research.ask_lifespan(lambda q: fixture("search_lifespan.json"), "Q?")
    years = [e["year"] for e in answer["events"]]
    assert 1779 in years and 2002 in years
    assert answer["citations"], "citations must survive parsing"
    assert all(c["url"].startswith("http") for c in answer["citations"])


def test_ask_lifespan_returns_search_snippets():
    answer = research.ask_lifespan(lambda q: fixture("search_lifespan.json"), "Q?")
    assert isinstance(answer["snippets"], list)


def test_lifespan_question_without_place():
    question = research.lifespan_question("Test Tower", "", {})
    assert "in  itself" not in question
    assert "Test Tower" in question


def test_ask_lifespan_rejects_garbage():
    with pytest.raises(research.ResearchError):
        research.ask_lifespan(lambda q: {"output": []}, "Q?")
    with pytest.raises(research.ResearchError):
        research.ask_lifespan(
            lambda q: {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "nope", "annotations": []}]}
                ]
            },
            "Q?",
        )


def cond(seg):
    return seg["state"]["condition"]


def test_build_timeline_states():
    events = [
        {"year": 1932, "event": "built", "detail": "Built."},
        {"year": 1986, "event": "restored", "detail": "Decorated.", "visible_change": "repainted"},
        {"year": 1987, "event": "repurposed", "detail": "Out of use."},
        {"year": 1999, "event": "rebuilt", "detail": "Rebuild started."},
        {"year": 2002, "event": "rebuilt", "detail": "Reopened."},
    ]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["to_year"], cond(s)) for s in segs] == [
        (1932, 1986, "standing"),
        (1986, 1999, "standing"),
        (1999, 2002, "under_construction"),
        (2002, None, "rebuilt"),
    ]
    assert segs[1]["state"]["description"] == "repainted"
    assert segs[0]["state"]["scope"] == "whole"


def test_build_timeline_records_description_provenance():
    events = [
        {"year": 1899, "event": "built", "detail": "Construction began."},
        {"year": 2016, "event": "restored", "detail": "Restored.",
         "visible_change": "new staircase fitted"},
    ]
    first, second = research.build_timeline(events)
    assert first["description_from"] == "detail"
    assert second["description_from"] == "visible_change"


def test_build_timeline_non_visible_events_leave_no_segment():
    events = [
        {"year": 1779, "event": "built", "detail": ""},
        {"year": 1802, "event": "repurposed", "detail": "Sold to a merchant."},
        {"year": 1964, "event": "heritage designation", "detail": "National Historic Landmark."},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["to_year"], cond(seg)) == (1779, None, "standing")


def test_build_timeline_same_year_last_state_wins():
    events = [
        {"year": 1932, "event": "burnt", "detail": ""},
        {"year": 1932, "event": "rebuilt", "detail": ""},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["to_year"], cond(seg)) == (1932, None, "rebuilt")


def test_build_timeline_decorated_with_tulips_is_visible():
    (seg,) = research.build_timeline(
        [{"year": 1986, "event": "decorated", "detail": "Decorated with tulips.",
          "visible_change": "decorated with tulips"}]
    )
    assert cond(seg) == "standing"
    assert seg["state"]["description"] == "decorated with tulips"


def test_build_timeline_reconstruction_is_ongoing():
    (seg,) = research.build_timeline(
        [{"year": 1999, "event": "reconstruction", "detail": "Work underway."}]
    )
    assert cond(seg) == "under_construction"


def test_build_timeline_unknown_event_without_visible_change_is_caption_only():
    assert research.build_timeline([{"year": 1967, "event": "moved-proposed", "detail": "Talks held."}]) == []


def test_build_timeline_skips_planned_but_prevented_changes():
    events = [
        {"year": 1920, "event": "extended", "detail": "Steam engine replaced."},
        {"year": 1925, "event": "demolished", "detail": "Demolition planned but prevented."},
        {"year": 1930, "event": "damaged", "detail": "Storm damage."},
    ]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["to_year"]) for s in segs] == [(1920, 1930), (1930, None)]


def test_build_timeline_keeps_planned_work_once_started():
    events = [{"year": 1999, "event": "rebuilt", "detail": "Rebuild planned; first pole put in ground."}]
    (seg,) = research.build_timeline(events)
    assert cond(seg) == "under_construction"


def test_build_timeline_skips_uncompleted_changes():
    events = [
        {"year": 1932, "event": "burnt", "detail": "Burnt down.", "completed": True},
        {"year": 1963, "event": "restored", "detail": "Rebuild promised; nothing happened.", "completed": False},
        {"year": 1999, "event": "rebuilt", "detail": "First pole in ground.", "completed": True},
    ]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["to_year"], cond(s)) for s in segs] == [
        (1932, 1999, "ruin"),
        (1999, None, "under_construction"),
    ]


def test_build_timeline_partly_claims_never_seed_states():
    events = [
        {"year": 1920, "event": "built", "detail": "Inception.", "verdict": "partly"},
        {"year": 1926, "event": "construction", "detail": "Work started.", "verdict": "supported"},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], cond(seg)) == (1926, "under_construction")


def test_build_timeline_part_scope_leaves_no_segment():
    events = [
        {"year": 1899, "event": "built", "detail": "Built."},
        {"year": 2009, "event": "demolished", "detail": "Small outbuildings removed."},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["to_year"], cond(seg)) == (1899, None, "standing")


def test_build_timeline_merges_only_identical_states():
    same = research.build_timeline(
        [
            {"year": 2003, "event": "restored", "detail": "Cleaned."},
            {"year": 2004, "event": "restored", "detail": "Cleaned."},
        ]
    )
    assert [(s["from_year"], s["to_year"]) for s in same] == [(2003, None)]
    different = research.build_timeline(
        [
            {"year": 2003, "event": "restored", "detail": "Cleaned."},
            {"year": 2004, "event": "restored", "detail": "Repainted."},
        ]
    )
    assert [(s["from_year"], cond(s)) for s in different] == [(2003, "standing"), (2004, "standing")]


def test_source_quality_rule():
    assert research.claim_quality_ok(["https://nl.wikipedia.org/wiki/X"]) is True
    assert research.claim_quality_ok(["https://www.tripadvisor.co.nz/abc"]) is False
    assert (
        research.claim_quality_ok(
            ["https://www.tripadvisor.co.nz/abc", "https://nl.wikipedia.org/wiki/X"]
        )
        is True
    )
    assert research.claim_quality_ok([]) is False
    assert research.is_weak_source("https://www.reddit.com/r/x") is True
    assert research.is_weak_source("https://www.molenadriaan.nl/en/timeline/") is False
    assert research.is_weak_source("https://aroundus.com/p/11888475-x") is True
    assert research.is_weak_source("https://wanderlog.com/places/x") is True
    assert research.is_weak_source("https://www.getyourguide.com/x-l147772/") is True
    assert research.is_weak_source("https://www.viator.com/tours/x/d1") is True
    assert research.claim_quality_ok(["https://aroundus.com/p/11888475-x"]) is False


def test_wikidata_claims_from_dated_statements():
    facts = {
        "facts": [
            {
                "property": "P571",
                "name": "inception",
                "value": {"time": "+1932-00-00T00:00:00Z", "precision": 9},
                "qualifiers": {},
                "references": [{"P854": ["https://example.com/archive"]}],
                "source": "https://www.wikidata.org/wiki/Q999#P571",
            }
        ]
    }
    (claim,) = research.wikidata_claims("Q999", facts)
    assert claim["year"] == 1932
    assert claim["kind"] == "object"
    assert claim["event"] == "built"
    assert "https://www.wikidata.org/wiki/Q999#P571" in claim["sources"]
    assert "https://example.com/archive" in claim["sources"]


def test_inception_with_reference_is_the_build_anchor():
    facts = {
        "facts": [
            {
                "property": "P571",
                "name": "inception",
                "value": {"time": "+1932-00-00T00:00:00Z", "precision": 9},
                "qualifiers": {},
                "references": [{"P854": ["https://example.com/archive"]}],
                "source": "https://www.wikidata.org/wiki/Q999#P571",
            }
        ]
    }
    (claim,) = research.wikidata_claims("Q999", facts)
    assert claim["anchor"] == "build"


def test_inception_without_reference_is_no_anchor():
    facts = {
        "facts": [
            {
                "property": "P571",
                "name": "inception",
                "value": {"time": "+1932-00-00T00:00:00Z", "precision": 9},
                "qualifiers": {},
                "references": [],
                "source": "https://www.wikidata.org/wiki/Q999#P571",
            }
        ]
    }
    (claim,) = research.wikidata_claims("Q999", facts)
    assert "anchor" not in claim


def test_opening_date_with_reference_is_the_build_anchor():
    facts = {
        "facts": [
            {
                "property": "P1619",
                "name": "date of official opening",
                "value": {"time": "+1934-05-01T00:00:00Z", "precision": 11},
                "qualifiers": {},
                "references": [{"P854": ["https://example.com/archive"]}],
                "source": "https://www.wikidata.org/wiki/Q999#P1619",
            }
        ]
    }
    (claim,) = research.wikidata_claims("Q999", facts)
    assert claim["event"] == "opened"
    assert claim["year"] == 1934
    assert claim["anchor"] == "build"


def test_assemble_claims_never_outvotes_the_anchor():
    events = [
        {"year": 1930, "event": "built", "detail": "Built in 1930."},
        {"year": 1932, "event": "built", "detail": "Built in 1932."},
        {"year": 1934, "event": "opened", "detail": "Opened in 1934."},
        {"year": 1940, "event": "burnt", "detail": "Burnt in 1940."},
    ]
    claims = research.assemble_claims(events=events, citations=[], sources=[], anchor_year=1932)
    assert [(c["year"], c["event"]) for c in claims] == [(1934, "opened"), (1940, "burnt")]
    kept = research.assemble_claims(events=events, citations=[], sources=[])
    assert len(kept) == 4


def test_wikidata_claims_skips_undated():
    facts = {"facts": [{"property": "P84", "name": "architect", "value": {"qid": "Q1", "label": "X"}, "qualifiers": {}, "references": [], "source": "u"}]}
    assert research.wikidata_claims("Q999", facts) == []


def test_wikidata_claims_format_dates_by_precision():
    facts = {
        "facts": [
            {
                "property": "P571",
                "name": "inception",
                "value": {"time": "+1932-00-00T00:00:00Z", "precision": 9},
                "qualifiers": {},
                "references": [],
                "source": "https://www.wikidata.org/wiki/Q999#P571",
            },
            {
                "property": "P793",
                "name": "significant event",
                "value": {"qid": "Q1", "label": "renovation"},
                "qualifiers": {"P585": [{"time": "+1960-00-00T00:00:00Z", "precision": 8}]},
                "references": [],
                "source": "https://www.wikidata.org/wiki/Q999#P793",
            },
        ]
    }
    claims = research.wikidata_claims("Q999", facts)
    assert [(c["event"], c["date_text"]) for c in claims] == [
        ("built", "in 1932"),
        ("renovation", "in the 1960s"),
    ]
    assert all("+" not in c["claim"] and "T00:00:00Z" not in c["claim"] for c in claims)


def test_wikidata_claims_name_thing_facts_for_meaning_classification():
    facts = {
        "facts": [
            {
                "property": "P84",
                "name": "architect",
                "value": {"qid": "Q1", "label": "Peter Hall"},
                "qualifiers": {"P585": [{"time": "+1966-00-00T00:00:00Z", "precision": 9}]},
                "references": [],
                "source": "https://www.wikidata.org/wiki/Q999#P84",
            }
        ]
    }
    (claim,) = research.wikidata_claims("Q999", facts)
    assert claim["event"] == "architect"
    assert claim["date_text"] == "in 1966"
    assert "Peter Hall" in claim["claim"]


def test_assemble_claims_dedupes_sources():
    claims = research.assemble_claims(
        events=[{"year": 1932, "event": "built", "detail": "Built in 1932."}],
        citations=[{"url": "https://nl.wikipedia.org/wiki/X", "title": "X"}],
        sources=["https://nl.wikipedia.org/wiki/X", "https://example.com/y"],
    )
    (claim,) = claims
    assert claim["year"] == 1932 and claim["kind"] == "object"
    assert sorted(claim["sources"]) == ["https://example.com/y", "https://nl.wikipedia.org/wiki/X"]
    assert "1932" in claim["claim"]


def test_assemble_claims_dates_the_claim_text():
    (claim,) = research.assemble_claims(
        events=[{"year": 1932, "event": "burnt",
                 "detail": "the mill burnt down",
                 "date_text": "23 April 1932"}],
        citations=[], sources=[])
    assert claim["claim"] == "burnt (23 April 1932): the mill burnt down"


def test_assemble_claims_ranges_stay_ranges_in_text():
    (claim,) = research.assemble_claims(
        events=[{"year": 1026, "event": "stood",
                 "detail": "thought to be old",
                 "date_text": "between 800 and 1,200 years old"}],
        citations=[], sources=[])
    assert "(between 800 and 1,200 years old)" in claim["claim"]
    assert "1026" not in claim["claim"]


def test_assemble_claims_carries_visible_change_and_date_text():
    (claim,) = research.assemble_claims(
        events=[
            {
                "year": 1026, "event": "built", "detail": "Thought to be 800 years old.",
                "visible_change": "", "date_text": "about 800 years old",
            }
        ],
        citations=[],
        sources=[],
    )
    assert claim["visible_change"] == ""
    assert claim["date_text"] == "about 800 years old"


def test_assemble_claims_drops_absurd_years():
    events = [
        {"year": -569997974, "event": "built", "detail": "Rocks formed."},
        {"year": 2999, "event": "built", "detail": "Not yet built."},
        {"year": "unknown", "event": "built", "detail": "No year given."},
        {"year": -5000, "event": "stood", "detail": "Ancient tree stood."},
        {"year": 1884, "event": "extended", "detail": "Railway opened."},
    ]
    claims = research.assemble_claims(events=events, citations=[], sources=[])
    assert [c["year"] for c in claims] == [-5000, 1884]


def test_lifespan_schema_asks_visible_change_and_vague_date():
    event = research.LIFESPAN_SCHEMA["properties"]["events"]["items"]
    assert set(event["required"]) == {"year", "event", "detail", "visible_change", "date_text"}
    question = research.lifespan_question("Oak", "Town", {})
    assert "visible" in question.lower()
    assert "date_text" in question or "vague date" in question.lower()


def test_lifespan_question_asks_ranges_as_ranges():
    question = research.lifespan_question("Oak", "Town", {})
    assert "range" in question.lower()
    assert "800" in question and "1,200" in question


def test_build_timeline_flags_implausible_span():
    events = [
        {"year": 1899, "event": "construction",
         "detail": "Construction began in 1899.", "visible_change": ""},
        {"year": 1953, "event": "demolished",
         "detail": "Foghorn taken down.", "visible_change": "foghorn removed"},
    ]
    segs = research.build_timeline(events)
    assert segs[0]["flag"] is not None
    assert "flag" not in segs[1] or segs[1].get("flag") is None


def test_build_timeline_carries_date_label():
    events = [
        {"year": 1026, "event": "built", "detail": "Old tree.",
         "date_text": "between 800 and 1,200 years old"},
    ]
    (seg,) = research.build_timeline(events)
    assert seg["date_label"] == "about 800 to 1,200 years old"
