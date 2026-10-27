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


def test_keep_quality_drops_weak_only_claims(capsys):
    from witness.cli import keep_quality

    good = kept_claim(1779, "built", "Built.")
    good["sources"] = ["https://en.wikipedia.org/wiki/X"]
    weak = kept_claim(1850, "stood", "Stood.")
    weak["sources"] = ["https://www.tripadvisor.example/x"]
    kept = keep_quality([good, weak])
    assert kept == [good]
    assert "weak sources only" in capsys.readouterr().out


def test_keep_quality_drops_exact_duplicate_claims(capsys):
    from witness.cli import keep_quality

    first = kept_claim(1905, "extended", "Extended with a wing.")
    first["sources"] = ["https://en.wikipedia.org/wiki/X"]
    kept = keep_quality([first, dict(first)])
    assert kept == [first]
    assert "duplicate" in capsys.readouterr().out


def test_plan_checks_covers_every_kept_claim_once_duplicates_dropped():
    from witness.cli import keep_quality, plan_checks

    kept = [kept_claim(1800 + i, "repainted", f"Repainted shade {i}.")
            for i in range(12)]
    for claim in kept:
        claim["sources"] = ["https://en.wikipedia.org/wiki/X"]
    dupe = kept_claim(1805, "extended", "Extended with a wing.")
    dupe["sources"] = ["https://en.wikipedia.org/wiki/X"]
    kept += [dupe, dict(dupe)]
    deduped = keep_quality(kept)
    assert len(deduped) == len(kept) - 1
    to_check, pool = plan_checks(deduped)
    assert len(to_check) + len(pool) == len(deduped)
    assert {id(c) for c in to_check + pool} == {id(c) for c in deduped}


def test_draft_scenes_match_plan_scene_years():
    from witness.cli import draft_scenes, plan_checks

    kept = [kept_claim(y, "stood", f"Stood in {y}.") for y in (1779, 1850, 1900)]
    draft = draft_scenes(kept)
    to_check, _ = plan_checks(kept)
    scene_years = {s["from_year"] for s in draft if isinstance(s["from_year"], int)}
    assert scene_years <= {c["year"] for c in to_check}


def test_report_and_save_writes_research_json(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from witness.cli import report_and_save

    monkeypatch.chdir(tmp_path)
    found = SimpleNamespace(name="Test Mill", kind="mill", qid="Q1",
                            articles={"en": "Test_Mill"})
    kept = [kept_claim(1779, "built", "Built in 1779.")]
    kept[0].update({"verdict": "supported", "quote": "q", "url": "u",
                    "support": [], "note": "", "completed": True,
                    "rewritten": None, "war_politics_only": False})
    timeline = [{"from_year": 1779, "to_year": None, "date_label": "1779",
                 "state": {"condition": "standing"}}]
    chosen = [{"from_year": 1779, "date_label": "1779",
               "state": {"condition": "standing"}, "reason": "built",
               "caption_lines": []}]
    result = {"outcome": "short_film", "reason": "test", "verified": 1,
              "eras": 1, "good_sources": 1}
    slug = report_and_save(found, "en", ["en"], kept, timeline, chosen, result,
                           {"total_s": 1.0}, "baseten", [], None)
    assert slug == "q1-test-mill"
    saved = (tmp_path / "out" / slug / "research.json").read_text()
    assert '"outcome": "short_film"' in saved


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


def test_build_jobs_runs_in_film_order():
    from witness.cli import build_jobs

    texts = {"https://en.wikipedia.org/wiki/X": "The mill was built in 1779. Storms hit in 1930."}
    claims = [
        {"year": 1930, "event": "damaged", "claim": "damaged 1930", "sources": ["https://en.wikipedia.org/wiki/X"]},
        {"year": 1779, "event": "built", "claim": "built 1779", "anchor": "build",
         "sources": ["https://en.wikipedia.org/wiki/X"]},
        {"year": 1850, "event": "stood", "claim": "stood 1850", "sources": ["https://en.wikipedia.org/wiki/X"]},
    ]
    jobs = build_jobs(claims, texts, [], 1779)
    assert [(j["year"], j.get("anchor")) for j in jobs] == [
        (1779, "build"), (1850, None), (1930, None)]
    assert [j["claim_index"] for j in jobs] == [1, 2, 0]


def test_apply_judged_maps_results_back_in_claim_order():
    from witness.cli import apply_judged

    claims = [{"year": 1930, "claim": "damaged 1930"}, {"year": 1779, "claim": "built 1779"}]
    jobs = [{"claim_index": 1}, {"claim_index": 0}]
    judged = [{"verdict": "supported", "war_politics_only": False},
              {"verdict": "unsupported", "war_politics_only": False}]
    apply_judged(claims, jobs, judged)
    assert [c["verdict"] for c in claims] == ["unsupported", "supported"]


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


def test_cli_progress_prints_source_errors_as_notes(capsys):
    from witness.cli import cli_progress

    cli_progress("source_error", {"source": "wikidata", "error": "busy backend"})
    cli_progress("verifying", {"claim": "x"})
    out = capsys.readouterr().out
    assert "note: wikidata failed: busy backend" in out
    assert "verifying" not in out


def test_film_facts_returns_anchor_without_research(monkeypatch, capsys):
    from types import SimpleNamespace
    from witness import cli as cli_module
    from witness import research as research_module

    monkeypatch.setattr(research_module, "fetch_facts",
                        lambda *a, **k: {"facts": [{"p": 1}]})
    monkeypatch.setattr(research_module, "wikidata_claims",
                        lambda qid, facts: [{"year": 1779, "anchor": "build"}])
    found = SimpleNamespace(qid="Q1", country_code="nl")
    timings = {}
    first = cli_module.film_facts(found, "en", None, timings)
    assert first["build_anchor_year"] == 1779
    assert first["claims"] == [{"year": 1779, "anchor": "build"}]
    assert "facts_s" in timings
    out = capsys.readouterr().out
    assert "build anchor: 1779 fixed by Wikidata" in out


def test_film_facts_without_qid_has_no_anchor(capsys):
    from types import SimpleNamespace
    from witness.cli import film_facts

    found = SimpleNamespace(qid=None, country_code=None)
    first = film_facts(found, "en", None, {})
    assert first["build_anchor_year"] is None
    assert first["claims"] == []


def test_cmd_paint_saves_eras_contact_sheet_and_manifest(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    tiny = buf.getvalue()
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    out_dir.mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Stands whole."},
             "caption_lines": []},
            {"from_year": "today", "date_label": "today",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": ""},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": f"r-{prev_id or 'none'}"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), "Test Town", mode="parallel",
        paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.")
    assert code == 0
    assert (out_dir / "eras_parallel" / "1850.png").exists()
    assert not (out_dir / "eras_parallel" / "today.png").exists()
    assert (out_dir / "eras_parallel" / "contact.png").exists()
    manifest = json.loads((out_dir / "paint_parallel.json").read_text())
    assert manifest["eras"] == [
        {"year": 1850, "verdict": "matches", "attempts": 1,
         "file": "eras_parallel/1850.png"}]
    assert manifest["mode"] == "parallel"


def test_cmd_paint_filters_scenes(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    tiny = buf.getvalue()
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    out_dir.mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
            {"from_year": 1950, "date_label": "1950",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)
    seen = []

    def fake_call(prompt, prev_id, photo_bytes=None):
        seen.append(prompt)
        return {"image": tiny, "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), "Test Town", mode="chain",
        scenes="1950", paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.")
    assert code == 0
    assert (out_dir / "eras_chain" / "1950.png").exists()
    assert not (out_dir / "eras_chain" / "1850.png").exists()
    assert len(seen) == 2  # anchor plus the one era
