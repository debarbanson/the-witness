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


def test_timeline_events_use_rewrite_words_for_partly_claims():
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
    assert events[1]["event"] == "" and "tulips" in events[1]["detail"]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1932, "standing"), (1986, "standing")]
    assert segs[1]["state"]["description"] == "tulips added"


def test_compare_verdicts_tallies_agreement():
    from witness.cli import compare_verdicts

    jobs = [{"claim": "a"}, {"claim": "b"}, {"claim": "c"}]
    meta = [{"verdict": "supported"}, {"verdict": "supported"}, {"verdict": "unsupported"}]
    alt = [{"verdict": "supported"}, {"verdict": "unsupported"}, {"verdict": "unsupported"}]
    compared = compare_verdicts(jobs, meta, alt)
    assert (compared["agree"], compared["total"]) == (2, 3)
    assert compared["disagree"] == [{"claim": "b", "meta": "supported", "alt": "unsupported"}]


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
