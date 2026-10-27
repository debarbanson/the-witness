"""CLI helpers: slugs for any script and any accents."""

from witness.cli import slug_for


def test_slug_transliterates_accents():
    assert slug_for("Biosphère", "Q123", {}) == "q123-biosphere"


def test_slug_falls_back_to_english_article():
    assert slug_for("錦帯橋", "Q1196460", {"en": "Kintai Bridge"}) == "q1196460-kintai-bridge"


def test_slug_falls_back_to_wikidata_id():
    assert slug_for("錦帯橋", "Q1196460", {}) == "q1196460"


def test_slug_without_qid():
    assert slug_for("De Adriaan", None, {}) == "de-adriaan"
    assert slug_for("???", None, {}) == "film"


def test_slug_prefers_reading_order():
    articles = {"nl": "Grote Eik van Sherwood", "en": "Major Oak"}
    assert slug_for("Major Oak", "Q388443", articles, prefer=("en",)) == "q388443-major-oak"
    assert slug_for("???", "Q388443", articles, prefer=("nl", "en")) == "q388443-grote-eik-van-sherwood"


def test_votes_for_build_anchor_and_state_setting_claims():
    from witness.cli import _votes_for

    assert _votes_for({"event": "built", "year": 1932}, "Built.") == 3
    assert _votes_for({"event": "renamed", "year": 1779}, "Renamed.", 1779) == 3
    assert _votes_for({"event": "burnt", "year": 1932}, "Burnt down.", 1779) == 3
    assert _votes_for({"event": "renamed", "year": 1900}, "Renamed.", 1779) == 1


def test_timeline_events_keep_event_for_partly_claims():
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1932, "event": "built", "verdict": "supported",
         "quote_span": "Built in 1932.", "completed": True, "visible_change": ""},
        {"year": 1986, "event": "restored", "verdict": "partly",
         "quote_span": "Action began to beautify the tower.",
         "rewritten": "Since 1986 the tower has been decorated with tulips.",
         "completed": True, "visible_change": "tulips added"},
        {"year": 1920, "event": "built", "verdict": "partly",
         "quote_span": "Inception in 1920.",
         "rewritten": "The project was proposed in 1920.",
         "completed": True, "visible_change": ""},
    ])
    assert events[1]["event"] == "restored" and "tulips" in events[1]["detail"]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1932, "standing"), (1986, "standing")]
    assert segs[1]["state"]["description"] == "tulips added"


def test_partly_reopening_after_fire_is_rebuilt_never_burnt():
    """De Adriaan 2002: context words ("70 years after fire") never set it."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1999, "event": "rebuilt", "verdict": "partly",
         "quote_span": "Rebuild started.", "rewritten": "Rebuilding started April 1999.",
         "completed": True, "visible_change": ""},
        {"year": 2002, "event": "rebuilt", "verdict": "partly",
         "quote_span": "Reopened.",
         "rewritten": "Rebuilt Adriaan reopened 23 April 2002, exactly 70 years "
                      "after fire, on original foundations.",
         "completed": True, "visible_change": "full windmill back on skyline"},
    ])
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1999, "under_construction"), (2002, "rebuilt")]


def test_partly_re_erection_after_flood_is_rebuilt_never_ruin():
    """Kintai 1674: destruction stated plus rebuild is genuine, not a facelift."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1673, "event": "built", "verdict": "supported",
         "quote_span": "Built in 1673.", "completed": True, "visible_change": ""},
        {"year": 1674, "event": "rebuilt", "verdict": "partly",
         "quote_span": "Rebuilt.",
         "rewritten": "The bridge was destroyed by a flood and was rebuilt in "
                      "1674 with improvements.",
         "completed": True, "visible_change": "bridge re-erected"},
    ])
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1673, "standing"), (1674, "rebuilt")]


def test_partly_build_finished_and_lit_is_standing():
    """Rubjerg 1899: first lighting is operational completion, not 54 years on site."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1899, "event": "built", "verdict": "partly",
         "quote_span": "Built.",
         "rewritten": "Construction began in 1899 on a lighthouse; light first "
                      "turned on 27 December 1900.",
         "completed": True, "visible_change": "new lighthouse built"},
    ])
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["state"]["condition"]) == (1899, "standing")


def test_removed_barracks_is_caption_not_demolished_tower():
    """Belem 1845: a gone ancillary part never demolishes the object."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1514, "event": "built", "verdict": "supported",
         "quote_span": "Built in 1514.", "completed": True, "visible_change": ""},
        {"year": 1845, "event": "demolished", "verdict": "supported",
         "quote_span": "The engineer demolished the Philippine barracks.",
         "completed": True, "visible_change": "barracks removed"},
    ])
    (seg,) = research.build_timeline(events)
    assert (seg["from_year"], seg["state"]["condition"]) == (1514, "standing")


def kept_claim(year, event, detail):
    return {"year": year, "event": event, "kind": "object",
            "claim": f"{event}: {detail}", "quote_span": detail,
            "date_text": "", "visible_change": "", "sources": ["https://example.com/x"]}


def test_plan_checks_covers_scenes_build_anchor_and_states():
    from witness.cli import plan_checks

    kept = [
        kept_claim(1779, "built", "Built in 1779."),
        kept_claim(1802, "repurposed", "Sold to a merchant."),
        kept_claim(1865, "extended", "Steam engine added."),
        kept_claim(1930, "damaged", "Storm damage."),
        kept_claim(1932, "burnt", "Burnt down."),
        kept_claim(1999, "rebuilt", "Rebuild started."),
        kept_claim(2002, "rebuilt", "Reopened."),
        kept_claim(2003, "repurposed", "Museum opened."),
        kept_claim(2004, "repurposed", "Weddings held."),
    ]
    to_check, pool = plan_checks(kept)
    years = {c["year"] for c in to_check}
    assert {1779, 1865, 1930, 1932, 1999, 2002} <= years  # anchor, build, states
    assert all(c in kept for c in to_check)
    assert len(to_check) + len(pool) == len(kept)
    assert not (set(map(id, to_check)) & set(map(id, pool)))


def test_spare_needs_counts_lineless_scenes():
    from witness.cli import spare_needs

    scenes = [
        {"from_year": 1779, "caption_lines": [{"year": 1802, "line": "sold"}]},
        {"from_year": 1932, "caption_lines": []},
        {"from_year": "today", "caption_lines": []},
    ]
    pool = [kept_claim(2003, "repurposed", "Museum opened.")]
    assert spare_needs(scenes, pool) == 1
    assert spare_needs(scenes, []) == 0
    full = [{"from_year": 1779, "caption_lines": [{"year": 1802, "line": "sold"}]}]
    assert spare_needs(full, pool) == 0


def test_cached_film_reused_within_a_week(tmp_path, monkeypatch):
    import json
    from datetime import date, timedelta
    from witness.cli import cached_film

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out" / "q1-tower"
    out.mkdir(parents=True)
    fresh = {"outcome": {"outcome": "short_film"},
             "saved_at": date.today().isoformat()}
    (out / "research.json").write_text(json.dumps(fresh))
    assert cached_film("q1-tower") == fresh
    stale = {"outcome": {"outcome": "short_film"},
             "saved_at": (date.today() - timedelta(days=8)).isoformat()}
    (out / "research.json").write_text(json.dumps(stale))
    assert cached_film("q1-tower") is None
    assert cached_film("missing-slug") is None


def test_describe_found_shows_kind_and_rejections():
    from witness.cli import describe_found

    class Found:
        name = "Heidelberger Schloss"
        kind = "wikidata item"
        description = "Schloss in Deutschland"
        rejected = ("Ruprechtsbau",)

    lines = describe_found(Found()).split("\n")
    assert lines[0] == "object: Heidelberger Schloss (Schloss in Deutschland)"
    assert lines[1] == "note: second look rejected Ruprechtsbau; retried"

    class Bare:
        name = "X"
        kind = "named place"

    assert describe_found(Bare()) == "object: X (named place)"


def test_claim_urls_skips_fetched_and_failed():
    from witness.cli import claim_urls

    claims = [{"sources": ["https://a.example/x", "https://b.example/y"]}]
    urls = claim_urls(claims, ["https://c.example/z"], {"https://a.example/x"}, {"https://c.example/z"})
    assert urls == ["https://b.example/y"]


def test_compare_verdicts_tallies_agreement():
    from witness.cli import compare_verdicts

    jobs = [{"claim": "a"}, {"claim": "b"}, {"claim": "c"}]
    meta = [{"verdict": "supported"}, {"verdict": "supported"}, {"verdict": "unsupported"}]
    alt = [{"verdict": "supported"}, {"verdict": "unsupported"}, {"verdict": "unsupported"}]
    compared = compare_verdicts(jobs, meta, alt)
    assert (compared["agree"], compared["total"]) == (2, 3)
    assert compared["providers"] == ["meta", "baseten"]
    assert compared["disagree"] == [{"claim": "b", "meta": "supported", "baseten": "unsupported"}]


def test_baseten_support_passes_timeout_and_falls_back_to_meta(monkeypatch):
    from witness import cli as cli_module
    from witness import models

    seen = {}

    class FakeChat:
        def create(self, **kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": '{"verdict": "supported"}'}}]}

    class FakeClient:
        chat = type("chat", (), {"completions": FakeChat()})()

    monkeypatch.setattr(cli_module, "_respond_for", lambda spec: FakeClient())
    shaped = cli_module.baseten_support_respond("claim")
    assert seen["timeout"] == 180
    assert seen["model"] == "meta-models/muse-spark-open-1026"
    assert shaped["output"][0]["content"][0]["text"] == '{"verdict": "supported"}'

    def boom(*args, **kwargs):
        raise RuntimeError("cold start")

    monkeypatch.setattr(models, "chat", boom)
    monkeypatch.setattr(cli_module, "support_respond", lambda prompt: {"fallback": True})
    assert cli_module.baseten_support_respond("claim") == {"fallback": True}


def test_keep_stores_reviewed_research(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    out_dir = tmp_path / "out" / "q1-test"
    out_dir.mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps(
        {"object": {"qid": "Q1", "lang": "en"}, "outcome": {"outcome": "short_film"}}))
    monkeypatch.chdir(tmp_path)
    assert cli_module.cmd_keep("q1-test") == 0
    from witness.cache import Cache
    assert Cache("out/cache").get_reviewed("Q1", "en")["outcome"]["outcome"] == "short_film"
    assert cli_module.cmd_keep("missing") == 2
