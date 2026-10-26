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


def test_lifespan_question_leads_with_local_article():
    question = research.lifespan_question(
        "Test Tower", "Test Town", {"nl": "Testtoren", "en": "Test Tower"}, lang="nl"
    )
    assert question.index("nl.wikipedia.org/wiki/Testtoren") < question.index("en.wikipedia")
    assert "Do not narrate" in question


def test_lifespan_question_prefers_user_language():
    question = research.lifespan_question(
        "Test Tower", "Test Town", {"nl": "Testtoren", "en": "Test Tower"}, lang="en"
    )
    assert question.index("en.wikipedia.org/wiki/Test_Tower") < question.index("nl.wikipedia")


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


def test_build_timeline_states():
    events = [
        {"year": 1932, "event": "built", "detail": "Built."},
        {"year": 1986, "event": "restored", "detail": "Decorated."},
        {"year": 1987, "event": "repurposed", "detail": "Out of use."},
        {"year": 1999, "event": "rebuilt", "detail": "Rebuild started."},
        {"year": 2002, "event": "rebuilt", "detail": "Reopened."},
    ]
    states = [(s["from_year"], s["to_year"], s["state"]) for s in research.build_timeline(events)]
    assert states == [
        (1932, 1986, "standing"),
        (1986, 1987, "restored"),
        (1987, 1999, "repurposed"),
        (1999, 2002, "under reconstruction"),
        (2002, None, "rebuilt"),
    ]


def test_build_timeline_decorated_is_restored():
    (seg,) = research.build_timeline([{"year": 1986, "event": "decorated", "detail": ""}])
    assert seg["state"] == "restored"


def test_build_timeline_merges_same_state_periods():
    events = [
        {"year": 1779, "event": "built", "detail": ""},
        {"year": 1779, "event": "built", "detail": ""},
        {"year": 1802, "event": "repurposed", "detail": ""},
    ]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["to_year"], s["state"]) for s in segs] == [
        (1779, 1802, "standing"),
        (1802, None, "repurposed"),
    ]


def test_build_timeline_same_year_last_state_wins():
    events = [
        {"year": 1932, "event": "burnt", "detail": ""},
        {"year": 1932, "event": "rebuilt", "detail": ""},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["to_year"], seg["state"]) == (1932, None, "rebuilt")


def test_build_timeline_decorated_with_tulips():
    (seg,) = research.build_timeline(
        [{"year": 1986, "event": "decorated", "detail": "Decorated with tulips."}]
    )
    assert seg["state"] == "decorated with tulips"
    (seg,) = research.build_timeline(
        [{"year": 1986, "event": "extended", "detail": "Meters-high tulip on all sides."}]
    )
    assert seg["state"] == "decorated with tulips"
    (seg,) = research.build_timeline(
        [{"year": 1986, "event": "extended", "detail": "Opgesierd met metershoge tulp."}]
    )
    assert seg["state"] == "decorated with tulips"


def test_build_timeline_reconstruction_is_ongoing():
    (seg,) = research.build_timeline(
        [{"year": 1999, "event": "reconstruction", "detail": "Work underway."}]
    )
    assert seg["state"] == "under reconstruction"


def test_build_timeline_unknown_event_uses_event_text():
    (seg,) = research.build_timeline([{"year": 1900, "event": "moved", "detail": ""}])
    assert seg["state"] == "moved"


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
    assert seg["state"] == "under reconstruction"


def test_build_timeline_merges_adjacent_equal_states():
    events = [
        {"year": 2003, "event": "repurposed", "detail": "Museum."},
        {"year": 2004, "event": "repurposed", "detail": "Weddings."},
    ]
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["to_year"], seg["state"]) == (2003, None, "repurposed")


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


def test_wikidata_claims_skips_undated():
    facts = {"facts": [{"property": "P84", "name": "architect", "value": {"qid": "Q1", "label": "X"}, "qualifiers": {}, "references": [], "source": "u"}]}
    assert research.wikidata_claims("Q999", facts) == []


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
