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


def test_report_and_save_prints_cost(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from witness.cli import report_and_save

    monkeypatch.chdir(tmp_path)
    found = SimpleNamespace(name="Test Mill", kind="mill", qid="Q1",
                            articles={"en": "Test_Mill"})
    result = {"outcome": "too_little", "reason": "test", "verified": 0,
              "eras": 0, "good_sources": 0}
    report_and_save(found, "en", ["en"], [], [], [], result, {}, "baseten", [],
                    None,
                    tokens={"meta": {"prompt_tokens": 8000, "completion_tokens": 0,
                                     "total_tokens": 8000}},
                    cost_usd=0.01)
    out, _ = capsys.readouterr()
    assert "cost: $0.01" in out
    saved = (tmp_path / "out" / "q1-test-mill" / "research.json").read_text()
    assert '"cost_usd": 0.01' in saved


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
             "object": {"lang": "en"},
             "saved_at": date.today().isoformat()}
    (out / "research.json").write_text(json.dumps(fresh))
    assert cached_film("q1-tower", "en") == fresh
    assert cached_film("q1-tower", "nl") is None
    stale = {"outcome": {"outcome": "short_film"},
             "object": {"lang": "en"},
             "saved_at": (date.today() - timedelta(days=8)).isoformat()}
    (out / "research.json").write_text(json.dumps(stale))
    assert cached_film("q1-tower", "en") is None
    assert cached_film("missing-slug", "en") is None


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


def test_dotenv_key_reaches_client_for(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WITNESS_TEST_KEY", raising=False)
    (tmp_path / ".env.local").write_text('WITNESS_TEST_KEY="t-abc"\n')
    cli_module.load_dotenv()
    spec = models.ModelSpec(provider="x", base_url="https://example.com/v1",
                            model="m", key_name="WITNESS_TEST_KEY")
    assert models.client_for(spec).api_key == "t-abc"


def test_dotenv_never_overrides_set_variables(tmp_path, monkeypatch, capsys):
    import os
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WITNESS_TEST_KEY", "keep")
    (tmp_path / ".env.local").write_text('WITNESS_TEST_KEY="t-abc"\nOTHER=hush\n')
    cli_module.load_dotenv()
    assert os.environ["WITNESS_TEST_KEY"] == "keep"
    assert os.environ["OTHER"] == "hush"
    assert capsys.readouterr().out == ""


def test_startup_arms_daily_cap(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WITNESS_DAILY_CAP_USD", raising=False)
    models.configure_spending(None)
    cli_module.startup()
    assert models._DAILY is not None
    assert models._DAILY.cap_usd == 25.0
    models.configure_spending(None)


def test_startup_cap_amount_from_env(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WITNESS_DAILY_CAP_USD", "5")
    models.configure_spending(None)
    cli_module.startup()
    assert models._DAILY.cap_usd == 5.0
    models.configure_spending(None)


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


def test_build_jobs_carries_date_and_backstops_yearless_text():
    from witness.cli import build_jobs

    claims = [
        {"year": 1865, "event": "converted", "claim": "converted to steam",
         "date_text": "1865", "sources": ["https://en.wikipedia.org/wiki/X"]},
        {"year": 1779, "event": "built", "claim": "built (in 1779): raised",
         "date_text": "in 1779", "sources": ["https://en.wikipedia.org/wiki/X"]},
    ]
    jobs = build_jobs(claims, {}, [], None)
    by_year = {j["year"]: j for j in jobs}
    assert by_year[1865]["claim"] == "converted to steam (1865)"
    assert by_year[1865]["date_text"] == "1865"
    assert by_year[1779]["claim"] == "built (in 1779): raised"
    assert by_year[1779]["date_text"] == "in 1779"


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


def test_caption_support_uses_three_votes(monkeypatch):
    from witness import cli as cli_module

    seen = {}

    def fake_judge(respond, job, completion=True):
        seen.update(job)
        return {"verdict": "supported"}

    monkeypatch.setattr(cli_module.verify, "judge_claim", fake_judge)
    out = cli_module.caption_support_respond(
        "I burnt down.", "The mill burnt down.")
    assert out == "supported"
    assert seen["votes"] == 3
    assert seen["passages"] == ["The mill burnt down."]


def test_baseten_support_falls_back_when_key_missing(monkeypatch):
    from witness import cli as cli_module

    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setattr(cli_module, "support_respond",
                        lambda prompt: {"fallback": True})
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
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1950, "verdict": "supported", "claim": "stood"}],
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
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: summer\nNone")
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
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1950, "verdict": "supported", "claim": "stood"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
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
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: summer\nNone")
    assert code == 0
    assert (out_dir / "eras_chain" / "1950.png").exists()
    assert not (out_dir / "eras_chain" / "1850.png").exists()
    assert len(seen) == 1  # the one era carries the photo, no spare turn


def test_cmd_paint_merges_manifest_and_contact_across_runs(tmp_path, monkeypatch):
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
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1950, "verdict": "supported", "claim": "stood"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
            {"from_year": 1950, "date_label": "1950",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": "r1"}

    for year in ("1850", "1950"):
        code = cli_module.cmd_paint(
            "q1-test", str(photo), "Test Town", mode="parallel",
            scenes=year, paint_call=fake_call,
            check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: summer\nNone")
        assert code == 0
    manifest = json.loads((out_dir / "paint_parallel.json").read_text())
    assert [e["year"] for e in manifest["eras"]] == [1850, 1950]
    sheet = Image.open(out_dir / "eras_parallel" / "contact.png")
    assert sheet.size[0] == 16  # both panels kept


def test_film_anchor_scene_paints_object_as_built():
    from witness import cli as cli_module

    scene = cli_module.film_anchor_scene("De Adriaan", 1779)
    assert scene["from_year"] == 1779
    assert scene["state"]["condition"] == "standing"
    assert "1779" in scene["state"]["description"]
    assert scene["caption_lines"] == []


def test_cmd_children_rewrites_lines_next_to_adult_ones(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    out_dir.mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": [
            {"year": 1802, "url": "https://example.com/x",
             "quote": "The mill was sold in 1802.",
             "verdict": "supported"},
            {"year": 1779, "url": "https://example.com/x",
             "quote": "The mill opened in 1779.",
             "verdict": "supported"},
        ],
        "scenes": [
            {"from_year": 1779, "date_label": "1779",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "opened in 1779"},
             "caption_lines": [
                 {"year": 1802, "line": "in 1802 sold",
                  "url": "https://example.com/x"},
                 {"year": 1900, "line": "no claim for this",
                  "url": "https://example.com/missing"},
             ]},
        ]}))

    code = cli_module.cmd_children(
        "q1-test",
        rewrite_call=lambda adult, source, plain: f"Little: {adult}",
        support_call=lambda line, source: "supported")
    assert code == 0
    data = json.loads((out_dir / "research.json").read_text())
    lines = data["scenes"][0]["caption_lines"]
    assert lines[0]["child"] == "Little: in 1802 sold"
    assert lines[0]["child_verified"] is True
    assert lines[1]["child"] is None
    assert data["scenes"][0]["child_state"] == "Little: opened in 1779"


def test_cmd_layers_saves_figure_layers(tmp_path, monkeypatch):
    import io
    import json
    from pathlib import Path
    from PIL import Image
    from witness import cli as cli_module

    raw = (Path(__file__).parent / "fixtures" / "sam_persons.txt").read_text()
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (200, 160), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())

    code = cli_module.cmd_layers("q1-test", mode="parallel",
                                 call_sam=lambda text, jpg: raw)
    assert code == 0
    saved = sorted((out_dir / "layers_parallel" / "1850").glob("*.png"))
    assert len(saved) == 2


def test_cmd_layers_clears_stale_and_records_source(tmp_path, monkeypatch):
    import hashlib
    import io
    import json
    from pathlib import Path
    from PIL import Image
    from witness import cli as cli_module

    raw = (Path(__file__).parent / "fixtures" / "sam_persons.txt").read_text()
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (200, 160), "red").save(buf, "PNG")
    painting = buf.getvalue()
    (era_dir / "1850.png").write_bytes(painting)
    stale_root = out_dir / "layers_parallel"
    (stale_root / "1850").mkdir(parents=True)
    (stale_root / "1850" / "figure_9.png").write_bytes(b"stale")
    (stale_root / "1950").mkdir(parents=True)
    (stale_root / "1950" / "figure_0.png").write_bytes(b"stale")

    code = cli_module.cmd_layers("q1-test", mode="parallel",
                                 call_sam=lambda text, jpg: raw)
    assert code == 0
    assert not (stale_root / "1950").exists()
    assert not (stale_root / "1850" / "figure_9.png").exists()
    source = json.loads((stale_root / "1850" / "source.json").read_text())
    assert source["sha256"] == hashlib.sha256(painting).hexdigest()


def test_cmd_paint_tag_saves_beside_earlier_runs(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    tiny = buf.getvalue()
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    (out_dir / "eras_parallel").mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1950, "verdict": "supported", "claim": "stood"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), "Test Town", mode="parallel", tag="b1",
        paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: summer\nNone")
    assert code == 0
    assert (out_dir / "eras_parallel_b1" / "1850.png").exists()
    assert (out_dir / "paint_parallel_b1.json").exists()
    assert not (out_dir / "paint_parallel.json").exists()


def test_cmd_render_builds_film_dir(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module
    from witness import segment as segment_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel_b1"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(buf.getvalue())
    cutout = segment_module.Cutout(
        (0, 0, 8, 8), 0.5, Image.new("L", (16, 24)),
        Image.new("RGBA", (16, 24), (1, 2, 3, 255)))

    code = cli_module.cmd_render(
        "q1-test", str(photo), subject="mill",
        era_dir="eras_parallel_b1", photo_credit="me",
        segment_call=lambda call_sam, path, subject: cutout)
    assert code == 0
    film_dir = out_dir / "film"
    assert (film_dir / "film.html").exists()
    assert (film_dir / "film.json").exists()
    assert (film_dir / "era_1850.jpg").exists()
    assert Image.open(film_dir / "era_1850.jpg").format == "JPEG"
    assert (film_dir / "today.jpg").exists()
    assert (film_dir / "cutout.png").exists()
    film = json.loads((film_dir / "film.json").read_text())
    assert film["object"] == "Test Mill"
    assert film["today_line"] == "And here I stand today."
    assert film["today_sub"] == ""
    assert film["scenes"][0]["caption"][0] == "1850"


def test_render_png_upload_serves_today_jpg(tmp_path, monkeypatch):
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel_b1"
    era_dir.mkdir(parents=True)
    Image.new("RGB", (16, 24), "red").save(era_dir / "1850.png")
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.png"
    exif = Image.Exif()
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N",
                   2: (52.0, 9.0, 36.0), 3: "E", 4: (4.0, 21.0, 0.0)}
    Image.new("RGB", (24, 16), "blue").save(photo, exif=exif)

    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1")
    assert code == 0
    film_dir = out_dir / "film"
    film = json.loads((film_dir / "film.json").read_text())
    assert film["photo"] == "today.jpg"
    assert (film_dir / "today.jpg").read_bytes()[:2] == b"\xff\xd8"
    assert dict(Image.open(film_dir / "today.jpg").getexif()) == {}


def test_render_without_subject_removes_stale_cutout(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo = _render_fixture(tmp_path)
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1}]}))
    stale = out_dir / "today_cutout.png"
    stale.write_bytes(b"previous-visitor-cutout")
    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1")
    assert code == 0
    assert not stale.exists()
    assert not (out_dir / "film" / "cutout.png").exists()


def test_film_cached_relay_current_photo(tmp_path, monkeypatch):
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo = _render_fixture(tmp_path)
    era_stream = out_dir / "eras_stream"
    era_stream.mkdir()
    Image.new("RGB", (16, 24), "red").save(era_stream / "1850.png")
    (out_dir / "paint_stream.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1}]}))
    film_dir = out_dir / "film"
    film_dir.mkdir()
    Image.new("RGB", (24, 16), "red").save(film_dir / "today.jpg")
    (film_dir / "film.html").write_text("<html>stale</html>")
    Image.new("RGB", (24, 16), "blue").save(photo)
    monkeypatch.setattr(cli_module, "run_job", lambda *a, **k: {
        "confirmed": True, "identified": True, "cached": "film",
        "slug": "q1-test", "result": {"outcome": "full_film"},
        "saved_at": "2026-10-29"})
    code = cli_module.cmd_film(str(photo), yes=True, out_dir=str(tmp_path / "out"))
    assert code == 0
    today = Image.open(film_dir / "today.jpg")
    assert today.getpixel((0, 0))[:3] != (255, 0, 0)
    assert (film_dir / "film.html").read_text() != "<html>stale</html>"


def test_film_cached_without_paintings_refuses(tmp_path, monkeypatch, capsys):
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    out_dir.mkdir(parents=True)
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [], "scenes": [],
        "timeline": []}))
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (24, 16), "blue").save(photo)
    monkeypatch.setattr(cli_module, "run_job", lambda *a, **k: {
        "confirmed": True, "identified": True, "cached": "reviewed",
        "slug": "q1-test", "result": {"outcome": "full_film"}})
    code = cli_module.cmd_film(str(photo), yes=True, out_dir=str(tmp_path / "out"))
    assert code == 2
    assert "opens instantly" not in capsys.readouterr().out


def test_collect_paint_entries_marks_crashed_future_dropped():
    from concurrent.futures import ThreadPoolExecutor
    from witness import cli as cli_module

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        def boom():
            raise RuntimeError("paint down")

        entries = cli_module.collect_paint_entries({1932: pool.submit(boom)})
        assert entries[1932]["verdict"] == "dropped"
        assert "paint down" in entries[1932]["note"]
    finally:
        pool.shutdown(cancel_futures=True)


def test_recover_or_retry_check_crash_keeps_dropped(tmp_path):
    from witness import cli as cli_module

    run_dir = tmp_path / "old"
    run_dir.mkdir()
    (run_dir / "1850.png").write_bytes(b"old-painting")
    scene = {"from_year": 1850,
             "state": {"condition": "damaged", "degree": "partial",
                       "scope": "whole", "description": "Roof holed."},
             "caption_lines": []}
    dropped = {"year": 1850, "image": None, "response_id": None,
               "verdict": "dropped", "attempts": 3, "note": "differed"}

    def checker(*args, **kwargs):
        raise RuntimeError("check down")

    result = cli_module.recover_or_retry(
        None, checker, scene, "Mill", "Town", None,
        {"season": "summer"}, [run_dir], dropped)
    assert result["verdict"] == "dropped"


def test_recover_or_retry_checks_only_two_newest_runs(tmp_path):
    from witness import cli as cli_module

    prior_dirs = []
    for tag in ("oldest", "middle", "newest"):
        run_dir = tmp_path / tag
        run_dir.mkdir()
        (run_dir / "1850.png").write_bytes(f"{tag}-painting".encode())
        prior_dirs.append(run_dir)
    prior_dirs.reverse()  # newest first, as cmd_paint passes them
    scene = {"from_year": 1850,
             "state": {"condition": "damaged", "degree": "partial",
                       "scope": "whole", "description": "Roof holed."},
             "caption_lines": []}
    dropped = {"year": 1850, "image": None, "response_id": None,
               "verdict": "dropped", "attempts": 3, "note": "differed"}
    seen = []

    def checker(image, prompt):
        seen.append(image)
        return "DIFFERS still."

    result = cli_module.recover_or_retry(
        None, checker, scene, "Mill", "Town", None,
        {"season": "summer"}, prior_dirs, dropped)
    assert result["verdict"] == "dropped"
    assert seen == [b"newest-painting", b"middle-painting"]


def test_stream_scene_kwargs_holds_back_unnamed_elements():
    from witness import cli as cli_module

    report = {"season": "summer", "elements": ["red car", "oak tree"]}
    claims = [{"year": 1900, "verdict": "supported",
               "claim": "A red car stood by the mill in 1900."},
              {"year": 1900, "verdict": "unsupported",
               "claim": "An oak tree shaded the yard."}]
    kwargs = cli_module.stream_scene_kwargs(
        report, claims, {"from_year": 1920})
    assert kwargs["season"] == "summer"
    assert kwargs["excluded"] == ("oak tree",)  # the car is verified named
    assert kwargs["claims"] == tuple(claims)


def test_stream_scene_kwargs_holds_back_everything_undated():
    from witness import cli as cli_module

    report = {"season": None, "elements": ["red car"]}
    kwargs = cli_module.stream_scene_kwargs(report, [], {})
    assert kwargs["season"] is None
    assert kwargs["excluded"] == ("red car",)


def test_future_response_id_none_when_scene_failed():
    from concurrent.futures import Future

    from witness import cli as cli_module

    good = Future()
    good.set_result({"response_id": "r1"})
    assert cli_module._future_response_id(good) == "r1"
    bad = Future()
    bad.set_exception(RuntimeError("paint down"))
    assert cli_module._future_response_id(bad) is None
    assert cli_module._future_response_id(None) is None  # no scene 1


class _UsageResponse:
    def __init__(self, payload, prompt, completion):
        self._payload = payload
        self.usage = {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": prompt + completion}

    def model_dump_json(self):
        import json

        return json.dumps(self._payload)


class _UsageClient:
    def __init__(self, payload, prompt=100, completion=50):
        self.payload = payload
        self.prompt = prompt
        self.completion = completion
        self.seen = {}

    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        self.seen.update(kwargs)
        return _UsageResponse(self.payload, self.prompt, self.completion)


def test_sam_respond_adds_segmentation_to_job_tally(monkeypatch):
    from witness import cli as cli_module
    from witness import models

    payload = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "mask here"}]}]}
    monkeypatch.setattr(cli_module, "_respond_for",
                        lambda spec: _UsageClient(payload))
    models.reset_usage()
    try:
        assert cli_module.sam_respond("cut out the mill", b"jpeg") == "mask here"
        assert models.usage_totals()["meta"]["total_tokens"] == 150
    finally:
        models.reset_usage()


def test_paint_respond_adds_image_to_job_tally(monkeypatch):
    import base64

    from witness import cli as cli_module
    from witness import models

    payload = {"id": "r1", "output": [
        {"type": "image_generation_call",
         "result": base64.b64encode(b"png").decode("ascii")}]}
    monkeypatch.setattr(cli_module, "_respond_for",
                        lambda spec: _UsageClient(payload))
    models.reset_usage()
    try:
        out = cli_module.paint_respond("paint it", None)
        assert out == {"image": b"png", "response_id": "r1"}
        assert models.usage_totals()["meta"]["total_tokens"] == 150
    finally:
        models.reset_usage()


def _render_fixture(tmp_path, slug="q1-test", root=None):
    import json
    from PIL import Image

    out_dir = (root or tmp_path / "out") / slug
    era_dir = out_dir / "eras_parallel_b1"
    era_dir.mkdir(parents=True)
    Image.new("RGB", (16, 24), "red").save(era_dir / "1850.png")
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (24, 16), "blue").save(photo)
    return out_dir, photo


def test_render_without_manifest_refuses(tmp_path, monkeypatch):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo = _render_fixture(tmp_path)
    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1")
    assert code == 2
    assert not (out_dir / "film").exists()


def test_render_ignores_paintings_missing_from_manifest(tmp_path, monkeypatch):
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo = _render_fixture(tmp_path)
    Image.new("RGB", (16, 24), "grey").save(
        out_dir / "eras_parallel_b1" / "1900.png")
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1},
                  {"year": 1900, "verdict": "dropped", "attempts": 3,
                   "note": "differed"}]}))
    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1")
    assert code == 0
    film = json.loads((out_dir / "film" / "film.json").read_text())
    assert [s["year"] for s in film["scenes"]] == [1850]
    assert not (out_dir / "film" / "era_1900.jpg").exists()


def test_verify_wiring_baseten_votes_completion_stays_meta():
    from witness import cli as cli_module
    from witness import models

    wiring = cli_module.verify_wiring("baseten")
    assert wiring["support"] is cli_module.baseten_support_respond
    assert wiring["completion"] is cli_module.support_respond
    assert wiring["workers"] == models.VERIFY_OPEN.workers


def test_verify_wiring_meta_and_both():
    from witness import cli as cli_module
    from witness import models

    meta = cli_module.verify_wiring("meta")
    assert meta["support"] is cli_module.support_respond
    assert meta["completion"] is cli_module.support_respond
    assert meta["workers"] == models.VERIFY.workers
    both = cli_module.verify_wiring("both")
    assert both["support"] is cli_module.support_respond
    assert both["completion"] is cli_module.support_respond


def test_judge_batch_uses_wiring_completion():
    import json as _json

    from witness import cli as cli_module

    seen = []

    def support(prompt):
        seen.append("support")
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps(
                 {"verdict": "supported", "quote": "Built in 1850 here.",
                  "url": "https://en.wikipedia.org/wiki/X",
                  "support": [{"url": "https://en.wikipedia.org/wiki/X",
                               "supports": True,
                               "quote": "Built in 1850 here."}]}),
             "annotations": []}]}]}

    def completion(prompt):
        seen.append("completion")
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": _json.dumps({"completed": True}),
             "annotations": []}]}]}

    wiring = {"support": support, "search": support,
              "completion": completion, "workers": 1}
    job = {"claim": "Built in 1850.", "event": "built",
           "detail": "Built in 1850.", "year": 1850, "date_text": "in 1850",
           "keywords": ["built"], "passages": ["Built in 1850 here."],
           "urls": ["https://en.wikipedia.org/wiki/X"], "votes": 1,
           "anchor": "build", "claim_index": 0}
    (judged,) = cli_module.judge_batch(wiring, [job], progress=None)
    assert judged["verdict"] == "supported"
    assert "support" in seen
    assert "completion" in seen


_JOB_WIKI = "https://en.wikipedia.org/wiki/Test_Mill"


def _job_found():
    from witness import identify

    return identify.Identification(
        name="Test Mill", kind="windmill", qid="Q1",
        articles={"en": "Test Mill"}, distance_m=10, confidence="high",
        candidates=(), country_code="NL")


def _job_first():
    return {"facts": {"facts": []},
            "claims": [{"year": 1850, "event": "built", "kind": "object",
                        "claim": "Built in 1850.",
                        "quote_span": "built in 1850",
                        "date_text": "in 1850", "visible_change": "",
                        "sources": [_JOB_WIKI], "anchor": "build"}],
            "build_anchor_year": 1850}


def _job_answer():
    return {"events": [{"year": 1900, "event": "damaged",
                        "detail": "roof holed in a storm",
                        "date_text": "in 1900", "visible_change": ""},
                       {"year": 1920, "event": "rebuilt",
                        "detail": "rebuilt after the storm",
                        "date_text": "in 1920", "visible_change": ""}],
            "sources": [],
            "citations": [{"url": _JOB_WIKI, "title": "Test Mill"}],
            "snippets": []}


def _answered(obj):
    import json as _json

    return {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": _json.dumps(obj),
         "annotations": []}]}]}


def _job_respond(prompt):
    if prompt.startswith("Claim:\n"):
        return _answered({"completed": True})
    claim_line = prompt.split("\n")[1] if prompt.startswith("Claim to check:") else prompt
    if "1850" in claim_line:
        quote = "Built in 1850 here."
    elif "1900" in claim_line:
        quote = "Roof holed in 1900."
    else:
        quote = "Rebuilt in 1920."
    return _answered(
        {"verdict": "supported", "quote": quote, "url": _JOB_WIKI,
         "support": [{"url": _JOB_WIKI, "supports": True,
                      "quote": quote}]})


class _JobTexts:
    def __init__(self, cache=None, progress=None):
        self.texts = {_JOB_WIKI: ("Built in 1850 here. Roof holed in 1900. "
                                        "Rebuilt in 1920.")}
        self.failures = []

    def fetch(self, claims, urls, verify_with, quiet=False):
        pass


def _stub_job(monkeypatch, calls=None):
    import types

    from witness import cli as cli_module
    from witness import identify as identify_module

    fake_identify = types.SimpleNamespace(
        identify=lambda *a, **k: _job_found(),
        capture_year=identify_module.capture_year,
        NoGpsError=identify_module.NoGpsError,
        NotIdentifiedError=identify_module.NotIdentifiedError,
        SourceError=identify_module.SourceError)
    monkeypatch.setattr(cli_module, "identify", fake_identify)
    monkeypatch.setattr(cli_module, "film_facts",
                        lambda *a, **k: _job_first())

    def ask(respond, question):
        if calls is not None:
            calls.append(question)
        return _job_answer()

    monkeypatch.setattr(cli_module.research, "ask_lifespan", ask)
    monkeypatch.setattr(cli_module, "SourceTexts", _JobTexts)
    monkeypatch.setattr(cli_module, "support_respond", _job_respond)
    monkeypatch.setattr(cli_module, "baseten_support_respond", _job_respond)
    monkeypatch.setattr(cli_module, "verify_respond", _job_respond)


def test_run_job_research_style_returns_filmable_result(tmp_path, monkeypatch):
    from witness import cli as cli_module

    _stub_job(monkeypatch)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"))
    assert result["confirmed"] is True
    assert result["cached"] is False
    assert [c["verdict"] for c in result["kept"]] == ["supported"] * 3
    assert [s["from_year"] for s in result["chosen"]] == [1850, 1900, 1920, "today"]
    assert result["result"]["outcome"] == "short_film"


def test_run_job_film_hooks_see_same_result(tmp_path, monkeypatch):
    from witness import cli as cli_module

    _stub_job(monkeypatch)
    seen = {"facts": [], "claims": [], "scenes": []}
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"),
        on_facts=lambda first: seen["facts"].append(first),
        on_claim=lambda index, claim: seen["claims"].append(claim["year"]),
        on_scene=lambda scene, number: seen["scenes"].append(scene["from_year"]))
    assert [s["from_year"] for s in result["chosen"]] == [1850, 1900, 1920, "today"]
    assert result["result"]["outcome"] == "short_film"
    assert seen["facts"] and seen["facts"][0]["build_anchor_year"] == 1850
    assert sorted(seen["claims"]) == [1850, 1900, 1920]
    assert seen["scenes"]  # draft scenes verified towards


def test_run_job_quiet_prints_nothing(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    _stub_job(monkeypatch)
    cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    out, _ = capsys.readouterr()
    assert out == ""


def test_run_job_declined_runs_no_research(tmp_path, monkeypatch):
    from witness import cli as cli_module

    calls = []
    _stub_job(monkeypatch, calls=calls)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: False, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result["confirmed"] is False
    assert calls == []
    assert result["spent"] == 0


def test_run_job_research_waits_for_confirm(tmp_path, monkeypatch):
    import time

    from witness import cli as cli_module

    calls = []
    _stub_job(monkeypatch, calls=calls)

    def slow_decide(found):
        time.sleep(0.5)
        assert calls == []  # nothing paid started during hesitation
        return True

    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=slow_decide, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result["confirmed"] is True
    assert len(calls) == 1


def test_run_job_returns_capped_when_cap_hit(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    _stub_job(monkeypatch)

    def capped(respond, question):
        raise models.SpendingCapExceeded(
            "daily spending cap reached ($1.00); try again tomorrow")

    monkeypatch.setattr(cli_module.research, "ask_lifespan", capped)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result.get("capped") is True
    assert "cap reached" in result["error"]


def test_run_job_result_carries_tokens_and_cost(tmp_path, monkeypatch):
    from witness import cli as cli_module

    _stub_job(monkeypatch)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result["tokens"] == {}
    assert result["cost_usd"] == 0  # stubs bypass paid calls


def test_run_job_maps_missing_location(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import identify as identify_module

    _stub_job(monkeypatch)

    def no_gps(*args, **kwargs):
        raise identify_module.NoGpsError("the photo carries no GPS data")

    monkeypatch.setattr(cli_module.identify, "identify", no_gps)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result["identified"] is False
    assert result["error_kind"] == "no_location"


def test_lat_lon_flags_reach_identify_as_location(tmp_path, monkeypatch):
    from witness import cli as cli_module

    seen = {}
    monkeypatch.setattr(cli_module, "cmd_identify",
                        lambda *a, **k: seen.update(k) or 0)
    code = cli_module.main(["identify", "p.jpg", "--lat", "52.1",
                            "--lon", "4.2"])
    assert code == 0
    assert seen["location"] == (52.1, 4.2)


def test_lat_without_lon_is_rejected(capsys):
    import pytest

    from witness import cli as cli_module

    with pytest.raises(SystemExit):
        cli_module.main(["identify", "p.jpg", "--lat", "52.1"])


def test_run_job_reuses_reviewed_cache(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness.cache import Cache

    calls = []
    _stub_job(monkeypatch, calls=calls)
    cache = Cache(str(tmp_path / "cache"))
    reviewed = {"outcome": {"outcome": "full_film"}, "claims": []}
    cache.put_reviewed("Q1", "en", reviewed)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True, no_cache=False,
        cache=cache, verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert result["confirmed"] is True
    assert result["cached"] == "reviewed"
    assert calls == []
    saved = tmp_path / "out" / result["slug"] / "research.json"
    assert saved.exists()


def test_render_mp4_failure_returns_error(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module
    from witness.render import record as render_record

    monkeypatch.setattr(cli_module, "cmd_render", lambda *a, **k: 0)

    def fail(*args, **kwargs):
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(render_record, "record", fail)
    code = cli_module.main(["render", "q1-test", "--photo", "p.jpg", "--mp4",
                            "--out-dir", str(tmp_path)])
    assert code == 1
    out, _ = capsys.readouterr()
    assert "MP4 recording failed" in out
    assert "MP4 at" not in out


def test_render_writes_into_job_folder(tmp_path, monkeypatch):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "jobs" / "j1"
    out_dir, photo = _render_fixture(tmp_path, root=root)
    import json
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1}]}))
    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1", out_dir=root)
    assert code == 0
    assert (root / "q1-test" / "film" / "film.html").exists()
    assert not (tmp_path / "out" / "q1-test").exists()


def test_final_paint_actions_paints_repaints_and_keeps():
    from witness import cli as cli_module

    standing = {"condition": "standing", "degree": "total", "scope": "whole",
                "description": "Whole."}
    burnt = {"condition": "burnt", "degree": "total", "scope": "whole",
             "description": "Burnt."}
    chosen = [{"from_year": 1779, "state": standing},
              {"from_year": 1932, "state": burnt},
              {"from_year": 1999, "state": standing}]
    actions = cli_module.final_paint_actions(
        chosen, {1779, 1999}, {1779: standing, 1999: burnt})
    assert actions == {1779: "keep", 1932: "paint", 1999: "repaint"}


def test_report_and_save_records_source_note(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    found = SimpleNamespace(name="Test Mill", kind="mill", qid="Q1",
                            articles={"en": "Test Mill"})
    kept = [
        {"year": 1779, "verdict": "supported", "claim": "built",
         "sources": ["https://en.wikipedia.org/wiki/X"],
         "url": "https://en.wikipedia.org/wiki/X"},
        {"year": 1865, "verdict": "supported", "claim": "stood",
         "sources": ["https://nl.wikipedia.org/wiki/Y"],
         "url": "https://nl.wikipedia.org/wiki/Y"},
        {"year": 1932, "verdict": "supported", "claim": "burnt",
         "sources": ["https://example.com/z"],
         "url": "https://example.com/z"},
    ]
    slug = cli_module.report_and_save(
        found, "en", ("en",), kept, [], [],
        {"outcome": "full_film", "reason": "x", "verified": 3, "eras": 3,
         "good_sources": 2}, {}, "meta", [], None)
    saved = json.loads((tmp_path / "out" / slug / "research.json").read_text())
    assert saved["source_note"] == {"distinct_sources": 2,
                                    "sites": ["Wikipedia", "example.com"]}


def test_report_and_save_writes_into_job_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    found = SimpleNamespace(name="Test Mill", kind="mill", qid="Q1",
                            articles={"en": "Test Mill"})
    root = tmp_path / "jobs" / "j1"
    slug = cli_module.report_and_save(
        found, "en", ("en",), [], [], [],
        {"outcome": "too_little", "reason": "x", "verified": 0, "eras": 0,
         "good_sources": 0}, {}, "meta", [], None, out_root=root)
    assert (root / slug / "research.json").exists()
    assert not (tmp_path / "out").exists()


def test_cmd_layers_tag_reads_tagged_eras(tmp_path, monkeypatch):
    import io
    from pathlib import Path
    from PIL import Image
    from witness import cli as cli_module

    raw = (Path(__file__).parent / "fixtures" / "sam_persons.txt").read_text()
    monkeypatch.chdir(tmp_path)
    era_dir = tmp_path / "out" / "q1-test" / "eras_parallel_b1"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (200, 160), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())

    code = cli_module.cmd_layers("q1-test", mode="parallel", tag="b1",
                                 call_sam=lambda text, jpg: raw)
    assert code == 0
    assert len(list((tmp_path / "out" / "q1-test" / "layers_parallel_b1" / "1850").glob("*.png"))) == 2


def _caption_research():
    return {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "claims": [
            {"year": 1779, "url": "https://a.example/x", "verdict": "supported",
             "claim": "opened in 1779", "rewritten": None,
             "quote": "The mill opened in 1779."},
            {"year": 1925, "url": "https://a.example/y", "verdict": "supported",
             "claim": "saved in 1925", "rewritten": None,
             "quote": "The mill was saved in 1925."},
        ],
        "scenes": [
            {"from_year": 1779, "date_label": "1779",
             "state": {"condition": "standing"}, "caption_lines": []},
            {"from_year": 1865, "date_label": "1865",
             "state": {"condition": "standing"}, "caption_lines": []},
        ],
    }


def test_cmd_captions_writes_sentence_and_skips_claimless(tmp_path, monkeypatch, capsys):
    import json
    from pathlib import Path
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))
    calls = []

    def rewrite(detail, quote, year, plain, stamp=""):
        calls.append((year, plain))
        return "I opened my doors to the town."

    code = cli_module.cmd_captions(
        "q1-test", rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported")
    assert code == 0
    assert calls == [(1779, False)]
    saved = json.loads((slug_dir / "research.json").read_text())
    first, second = saved["scenes"]
    assert first["caption_sentence"] == {
        "text": "I opened my doors to the town.",
        "claim_year": 1779, "claim_url": "https://a.example/x"}
    assert "caption_sentence" not in second


def test_cmd_captions_stops_cleanly_on_cap(tmp_path, monkeypatch, capsys):
    import json
    from pathlib import Path
    from witness import cli as cli_module
    from witness import models

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))

    def capped(*args, **kwargs):
        raise models.SpendingCapExceeded("daily spending cap reached")

    code = cli_module.cmd_captions(
        "q1-test", rewrite_call=capped,
        support_call=lambda sentence, quote: "supported")
    assert code == 2
    out, _ = capsys.readouterr()
    assert "spending cap" in out
    assert (slug_dir / "research.json").exists()


def test_cmd_layers_stops_cleanly_on_cap(tmp_path, monkeypatch, capsys):
    import io
    from PIL import Image
    from witness import cli as cli_module
    from witness import models

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (200, 160), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())

    def capped(text, jpg):
        raise models.SpendingCapExceeded("daily spending cap reached")

    code = cli_module.cmd_layers("q1-test", mode="parallel", call_sam=capped)
    assert code == 2
    out, _ = capsys.readouterr()
    assert "spending cap" in out


def test_cmd_captions_skips_captioned_scenes(tmp_path, monkeypatch, capsys):
    import json
    from pathlib import Path
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors.", "claim_year": 1779,
        "claim_url": "https://a.example/x"}
    (slug_dir / "research.json").write_text(json.dumps(data))
    calls = []

    def rewrite(detail, quote, year, plain, stamp=""):
        calls.append(year)
        return "I opened my doors."

    code = cli_module.cmd_captions(
        "q1-test", rewrite_call=rewrite,
        support_call=lambda sentence, quote: "supported")
    assert code == 0
    assert calls == []
    out, _ = capsys.readouterr()
    assert "no claim" in out


def test_cmd_captions_reports_failed_scenes(tmp_path, monkeypatch, capsys):
    import json
    from pathlib import Path
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "x" * 200,
        support_call=lambda sentence, quote: "supported")
    assert code == 1
    saved = json.loads((tmp_path / "out" / "q1-test" / "research.json").read_text())
    assert "caption_sentence" not in saved["scenes"][0]
    assert "caption_sentence" not in saved["scenes"][1]


def test_cmd_paint_recovers_dropped_critical_era(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module
    from witness import paint as paint_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    old_dir = slug_dir / "eras_parallel"
    old_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "grey").save(buf, "PNG")
    (old_dir / "1932.png").write_bytes(buf.getvalue())
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "photo.jpg")
    (slug_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "claims": [{"year": 1932, "verdict": "supported",
                    "claim": "burnt in 1932"}],
        "scenes": [
            {"from_year": 1932, "date_label": "1932",
             "state": {"condition": "ruin", "degree": "total",
                       "scope": "whole",
                       "description": "Only stones and beams left."},
             "caption_lines": [],
             "caption_sentence": {"text": "I burnt down in the evening.",
                                 "claim_year": 1932, "claim_url": "u"}},
        ],
    }))

    def blocked(prompt, prev_id, photo_bytes=None):
        raise paint_module.PaintSafetyError("content_policy_violation")

    code = cli_module.cmd_paint(
        "q1-test", str(tmp_path / "photo.jpg"), place="Town", tag="b1",
        paint_call=blocked, check_call=lambda image, p: "MATCHES base only.",
        photo_call=lambda photo_bytes, prompt: "winter")
    assert code == 0
    manifest = json.loads((slug_dir / "paint_parallel_b1.json").read_text())
    (entry,) = manifest["eras"]
    assert entry["verdict"] == "recovered"
    assert (slug_dir / "eras_parallel_b1" / "1932.png").read_bytes() == buf.getvalue()


def test_cmd_paint_skips_age_range_scenes(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "photo.jpg")
    (slug_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Oak", "qid": "Q1", "lang": "en"},
        "claims": [{"year": 1790, "verdict": "supported",
                    "claim": "named in 1790"}],
        "timeline": [], "timings": {},
        "scenes": [
            {"from_year": 1026, "date_label": "about 800 to 1,200 years old",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": ""},
             "caption_lines": []},
            {"from_year": 1790, "date_label": "1790",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
        ],
    }))
    painted = []

    def call(prompt, prev_id, photo_bytes=None):
        painted.append("1790" in prompt)
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "green").save(buf, "PNG")
        return {"image": buf.getvalue(), "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(tmp_path / "photo.jpg"), place="Forest",
        paint_call=call, check_call=lambda image, p: "MATCHES whole.",
        photo_call=lambda photo_bytes, prompt: "summer")
    assert code == 0
    assert painted == [True]
    assert not (slug_dir / "eras_parallel" / "1026.png").exists()


def test_cmd_paint_skips_scenes_without_supported_claims(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "photo.jpg")
    (slug_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Oak", "qid": "Q1", "lang": "en"},
        "claims": [{"year": 1790, "verdict": "supported",
                    "claim": "named in 1790"},
                   {"year": 1970, "verdict": "unsupported",
                    "claim": "scaffolded in 1970"}],
        "timeline": [], "timings": {},
        "scenes": [
            {"from_year": 1790, "date_label": "1790",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
            {"from_year": 1970, "date_label": "1970",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Scaffolded."},
             "caption_lines": []},
        ],
    }))
    painted = []

    def call(prompt, prev_id, photo_bytes=None):
        painted.append("1970" in prompt)
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "green").save(buf, "PNG")
        return {"image": buf.getvalue(), "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(tmp_path / "photo.jpg"), place="Forest",
        paint_call=call, check_call=lambda image, p: "MATCHES whole.",
        photo_call=lambda photo_bytes, prompt: "summer")
    assert code == 0
    assert painted == [False]
    assert not (slug_dir / "eras_parallel" / "1970.png").exists()
    manifest = json.loads((slug_dir / "paint_parallel.json").read_text())
    assert {e["year"]: e["verdict"] for e in manifest["eras"]} == {
        1790: "matches", 1970: "skipped"}
