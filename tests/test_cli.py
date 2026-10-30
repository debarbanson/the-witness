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


def test_caption_support_runs_on_bound_passages(monkeypatch):
    import json as _json

    from witness import cli as cli_module

    passage = ("https://a.example/mill\n"
               "The mill burnt down in 1932 after a lightning strike.")

    def respond(prompt):
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps(
                 {"verdict": "supported",
                  "quote": "The mill burnt down in 1932 after a lightning strike.",
                  "url": "https://a.example/mill",
                  "support": [{"url": "https://a.example/mill",
                               "supports": True,
                               "quote": "The mill burnt down in 1932 "
                                        "after a lightning strike."}]}),
             "annotations": []}]}]}

    monkeypatch.setattr(cli_module, "baseten_support_respond", respond)
    assert cli_module.caption_support_respond(
        "I burnt down.", [passage])["verdict"] == "supported"
    assert cli_module.child_support_respond(
        "I burnt down.", [passage])["verdict"] == "supported"


def test_visible_change_kept_only_when_the_quote_states_it():
    import json as _json

    from witness import cli as cli_module

    quote = "The mill burnt down in 1932, leaving only the brick base."

    def support(prompt):
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps(
                 {"verdict": "supported", "quote": quote,
                  "url": "https://a.example/mill",
                  "support": [{"url": "https://a.example/mill",
                               "supports": True, "quote": quote}]}),
             "annotations": []}]}]}

    def deny(prompt):
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps(
                 {"verdict": "unsupported", "quote": "",
                  "url": "https://a.example/mill",
                  "support": [{"url": "https://a.example/mill",
                               "supports": False, "quote": ""}]}),
             "annotations": []}]}]}

    kept = {"year": 1932, "verdict": "supported",
            "url": "https://a.example/mill", "quote": quote,
            "visible_change": "only the brick base left"}
    assert cli_module.verify_visible_changes(
        [kept], support, "Mill") == []
    assert kept["visible_change"] == "only the brick base left"
    dropped = dict(kept, visible_change="a new copper roof")
    assert cli_module.verify_visible_changes(
        [dropped], deny, "Mill") == [1932]
    assert dropped["visible_change"] == ""
    assert "accepted quote" in dropped["visible_change_note"]


def test_caption_support_binds_year_keywords_and_numbers(monkeypatch):
    from witness import cli as cli_module

    quote = "The mill burnt down in 1932 after a lightning strike."
    passage = f"https://a.example/mill\n{quote}"
    seen = {}

    def fake_judge(respond, job, completion=True):
        seen.update(job)
        return {"verdict": "supported", "quote": quote,
                "url": "https://a.example/mill"}

    monkeypatch.setattr(cli_module.verify, "judge_claim", fake_judge)
    out = cli_module.caption_support_respond(
        "In 1932, Mill: I burnt down.", [passage], 1932, ["burnt", "mill"])
    assert out == {"verdict": "supported", "quote": quote,
                   "url": "https://a.example/mill"}
    assert seen["year"] == 1932
    assert seen["keywords"] == ["burnt", "mill"]
    assert seen["votes"] == 3


def test_caption_support_rejects_unquoted_numbers_without_a_call(monkeypatch):
    from witness import cli as cli_module

    called = []

    def fake_judge(respond, job, completion=True):
        called.append(job)
        return {"verdict": "supported", "quote": "", "url": ""}

    monkeypatch.setattr(cli_module.verify, "judge_claim", fake_judge)
    out = cli_module.caption_support_respond(
        "In 1900, Tower: I was 236 years old when my sails were replaced.",
        ["https://en.wikipedia.org/wiki/Tower\n"
         "The tower was finished in 1664 on the dike.",
         "https://en.wikipedia.org/wiki/Tower\n"
         "The sails of the tower were replaced in 1950 after a storm."],
        1900, ["sails", "replaced"])
    assert out["verdict"] == "unsupported"
    assert called == []


def test_cli_has_no_layers_command(capsys):
    import pytest

    from witness import cli as cli_module

    assert not hasattr(cli_module, "cmd_layers")
    with pytest.raises(SystemExit):
        cli_module.main(["layers", "q1-test"])


def test_run_job_blanks_visible_change_missing_from_quote(tmp_path, monkeypatch):
    from witness import cli as cli_module

    _stub_job(monkeypatch)

    def denying(prompt):
        lines = prompt.split("\n")
        claim_line = lines[1] if len(lines) > 1 else prompt
        if claim_line.startswith("In ") and ", Test Mill: " in claim_line:
            return _answered(
                {"verdict": "unsupported", "quote": "",
                 "url": _JOB_WIKI,
                 "support": [{"url": _JOB_WIKI, "supports": False,
                              "quote": ""}]})
        return _job_respond(prompt)

    monkeypatch.setattr(cli_module, "support_respond", denying)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"))
    assert [c["verdict"] for c in result["kept"]] == ["supported"] * 3
    assert [c["visible_change"] for c in result["kept"]] == ["", "", ""]
    assert all("accepted quote" in c["visible_change_note"]
               for c in result["kept"])


def test_run_job_paints_no_blanked_visible_change(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import research as research_module

    _stub_job(monkeypatch)

    def inventing(respond, question):
        answer = _job_answer()
        answer["events"][0]["detail"] = (
            "roof holed in a storm, golden weathercock torn away")
        answer["events"][0]["visible_change"] = (
            "roof holed, golden weathercock gone")
        return answer

    monkeypatch.setattr(research_module, "ask_lifespan", inventing)

    def denying(prompt):
        lines = prompt.split("\n")
        claim_line = lines[1] if len(lines) > 1 else prompt
        if claim_line.startswith("In ") and ", Test Mill: " in claim_line:
            return _answered(
                {"verdict": "unsupported", "quote": "",
                 "url": _JOB_WIKI,
                 "support": [{"url": _JOB_WIKI, "supports": False,
                              "quote": ""}]})
        return _job_respond(prompt)

    monkeypatch.setattr(cli_module, "support_respond", denying)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"))
    scene = next(s for s in result["chosen"] if s["from_year"] == 1900)
    assert "golden" not in scene["state"]["description"]
    assert scene["state"]["description"] == ""


def test_run_job_refuses_a_war_subject_before_research(tmp_path, monkeypatch):
    import types

    from witness import cli as cli_module
    from witness import identify as identify_module

    _stub_job(monkeypatch)
    found = _job_found()
    object.__setattr__(found, "name", "War Memorial Park")
    monkeypatch.setattr(
        cli_module, "identify", types.SimpleNamespace(
            identify=lambda *a, **k: found,
            capture_year=identify_module.capture_year,
            NoGpsError=identify_module.NoGpsError,
            NotIdentifiedError=identify_module.NotIdentifiedError,
            SourceError=identify_module.SourceError))

    def bomb(respond, question):
        raise AssertionError("research must not run for a refused object")

    monkeypatch.setattr(cli_module.research, "ask_lifespan", bomb)
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"))
    assert result["confirmed"] is True
    assert result["result"]["outcome"] == "too_little"
    assert "war subject" in result["result"]["reason"]
    assert result["chosen"] == []


def test_cmd_children_writes_sentence_next_to_adult_one(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors to the town.", "claim_year": 1779,
        "claim_url": "https://a.example/x",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill opened in 1779."}}
    data["scenes"][0]["state"] = {"condition": "standing"}
    (slug_dir / "research.json").write_text(json.dumps(data))

    code = cli_module.cmd_children(
        "q1-test",
        rewrite_call=lambda adult, source, plain, gentle=False, stamp="": "I opened long ago.",
        support_call=lambda line, passages, *a: "supported")
    assert code == 0
    saved = json.loads((slug_dir / "research.json").read_text())
    child = saved["scenes"][0]["caption_sentence"]["child"]
    assert child == {"text": "I opened long ago."}
    assert "child" not in saved["scenes"][1].get("caption_sentence", {})


def test_cmd_children_judges_lines_with_object_context(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors to the town.", "claim_year": 1779,
        "claim_url": "https://a.example/x",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill opened in 1779."}}
    data["scenes"][0]["state"] = {"condition": "standing"}
    (slug_dir / "research.json").write_text(json.dumps(data))
    seen = []

    def support(line, passages, *a):
        seen.append(line)
        return "supported"

    code = cli_module.cmd_children(
        "q1-test",
        rewrite_call=lambda adult, source, plain, gentle=False, stamp="": "I opened long ago.",
        support_call=support)
    assert code == 0
    assert seen[0] == "In 1779, Mill: I opened long ago."


def test_cmd_children_judges_against_cached_article_text(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module
    from witness.cache import Cache

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors to the town.", "claim_year": 1779,
        "claim_url": "https://rich-children.example/mill",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://rich-children.example/mill",
                     "quote": "The mill opened in 1779."}}
    data["scenes"][0]["state"] = {"condition": "standing"}
    (slug_dir / "research.json").write_text(json.dumps(data))
    cache = Cache(tmp_path / "cache")
    cache.put("https://rich-children.example/mill",
              "The old mill stood by the river for many years.\n\n"
              "The mill opened in 1779 after years of building work.")
    seen = []

    def support(line, passages, *a):
        seen.extend(passages)
        return "supported"

    code = cli_module.cmd_children(
        "q1-test",
        rewrite_call=lambda adult, source, plain, gentle=False, stamp="": "I opened long ago.",
        support_call=support, cache=cache)
    assert code == 0
    assert any("years of building work" in p for p in seen)


def test_cmd_children_stamps_scene_sentences_not_lines(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors to the town.", "claim_year": 1779,
        "claim_url": "https://a.example/x",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill opened in 1779."}}
    data["scenes"][0]["state"] = {"condition": "standing"}
    (slug_dir / "research.json").write_text(json.dumps(data))
    seen = []

    def rewrite(adult, source, plain, gentle=False, stamp=""):
        seen.append(stamp)
        return "I opened long ago."

    code = cli_module.cmd_children("q1-test", rewrite_call=rewrite,
                                   support_call=lambda line, passages, *a: "supported")
    assert code == 0
    assert seen == ["1779"]


def test_cmd_children_marks_heavy_scenes_gentle(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I burnt down.", "claim_year": 1779,
        "claim_url": "https://a.example/x",
        "evidence": {"claim": "burnt in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill burnt down in 1779."}}
    data["scenes"][0]["state"] = {"condition": "burnt"}
    (slug_dir / "research.json").write_text(json.dumps(data))
    seen = {}

    def rewrite(adult, source, plain, gentle=False, stamp=""):
        seen["gentle"] = gentle
        return "I caught fire."

    code = cli_module.cmd_children(
        "q1-test", rewrite_call=rewrite,
        support_call=lambda line, passages, *a: "supported")
    assert code == 0
    assert seen["gentle"] is True


def test_child_rewrite_marks_gentle(monkeypatch):
    import json as _json

    from witness import cli as cli_module

    seen = {}

    class Resp:
        def model_dump_json(self):
            return _json.dumps(
                {"output": [{"content": [{"type": "output_text",
                                         "text": "Little line"}]}]})

    def fake_respond(*args, **kwargs):
        seen["prompt"] = kwargs.get("input", "")
        return Resp()

    monkeypatch.setattr(cli_module.models, "respond", fake_respond)
    assert cli_module.child_rewrite_respond("adult", "source", False) == "Little line"
    assert "gently" not in seen["prompt"]
    cli_module.child_rewrite_respond("adult", "source", False, gentle=True)
    assert "gently" in seen["prompt"]


def test_cmd_paint_child_writes_its_own_set(tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "photo.jpg")
    (slug_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "claims": [{"year": 1850, "verdict": "supported", "claim": "opened in 1850"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "child": {"text": "I opened long ago."}}},
        ],
    }))
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "grey").save(buf, "PNG")
    png = buf.getvalue()
    seen = {}

    def call(prompt, prev_id, photo_bytes=None):
        seen["prompt"] = prompt
        return {"image": png, "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(tmp_path / "photo.jpg"), audience="child",
        paint_call=call, check_call=lambda image, p: "MATCHES whole.",
        photo_call=lambda photo_bytes, prompt: "summer")
    assert code == 0
    assert "picture-book" in seen["prompt"]
    assert (slug_dir / "eras_parallel_child" / "1850.png").exists()
    manifest = json.loads((slug_dir / "paint_parallel_child.json").read_text())
    assert manifest["audience"] == "child"
    assert manifest["eras"][0]["caption"] == "I opened long ago."


def test_cmd_captions_rechecks_child_paintings_against_child_lines(
        tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    era_dir = slug_dir / "eras_parallel_child"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "grey").save(buf, "PNG")
    (era_dir / "1779.png").write_bytes(buf.getvalue())
    data = _caption_research()
    data["scenes"][0]["caption_sentence"] = {
        "text": "I opened my doors.", "claim_year": 1779,
        "claim_url": "https://a.example/x",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill opened in 1779."},
        "child": {"text": "I opened long ago."}}
    (slug_dir / "research.json").write_text(json.dumps(data))
    (slug_dir / "paint_parallel_child.json").write_text(json.dumps(
        {"audience": "child",
         "eras": [{"year": 1779, "verdict": "matches", "attempts": 1,
                   "file": "eras_parallel_child/1779.png",
                   "caption": "I opened my ancient doors."}]}))
    checked = []

    def check(image, prompt):
        checked.append(prompt)
        return "MATCHES whole mill."

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I opened my doors.",
        support_call=lambda sentence, passages, *a: "supported",
        check_call=check)
    assert code == 0
    assert len(checked) == 1
    assert "I opened long ago." in checked[0]
    manifest = json.loads((slug_dir / "paint_parallel_child.json").read_text())
    assert manifest["eras"][0]["caption"] == "I opened long ago."


def test_refresh_film_drops_partly_claims():
    from witness.cli import refresh_film

    kept = [
        {"year": 1932, "event": "built", "verdict": "supported",
         "claim": "Built in 1932.", "quote_span": "Built in 1932.",
         "completed": True, "visible_change": "", "date_text": "in 1932"},
        {"year": 1986, "event": "restored", "verdict": "partly",
         "claim": "Restored in 1986.", "quote_span": "Restored in 1986.",
         "rewritten": "Decorated in 1986.", "completed": True,
         "visible_change": "", "date_text": "in 1986"},
    ]
    verified, timeline, chosen = refresh_film(kept)
    assert [c["year"] for c in verified] == [1932]
    assert [s["from_year"] for s in timeline] == [1932]
    assert all(s["from_year"] != 1986 for s in chosen)


def test_refresh_film_drops_refused_claims():
    from witness.cli import refresh_film

    kept = [
        {"year": 1932, "event": "built", "verdict": "supported",
         "claim": "Built in 1932.", "quote_span": "Built in 1932.",
         "completed": True, "visible_change": "", "date_text": "in 1932"},
        {"year": 1944, "event": "damaged", "verdict": "supported",
         "claim": "Shelled in 1944.", "quote_span": "Shelled in 1944.",
         "completed": True, "visible_change": "", "date_text": "in 1944",
         "war_politics_only": True},
        {"year": 1952, "event": "stood", "verdict": "supported",
         "claim": "A wedding in 1952.", "quote_span": "A wedding in 1952.",
         "completed": True, "visible_change": "", "date_text": "in 1952",
         "refused_content": True},
    ]
    verified, timeline, chosen = refresh_film(kept)
    assert [c["year"] for c in verified] == [1932]
    assert [s["from_year"] for s in timeline] == [1932]
    assert {s["from_year"] for s in chosen} <= {1932, "today"}


def test_timeline_events_keep_event_for_supported_claims():
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1932, "event": "built", "verdict": "supported",
         "quote_span": "Built in 1932.", "completed": True, "visible_change": ""},
        {"year": 1986, "event": "restored", "verdict": "supported",
         "quote_span": "Since 1986 the tower has been decorated with tulips.",
         "completed": True, "visible_change": "tulips added"},
        {"year": 1920, "event": "built", "verdict": "supported",
         "quote_span": "The project was proposed in 1920.",
         "completed": False, "visible_change": ""},
    ])
    assert events[1]["event"] == "restored" and "tulips" in events[1]["detail"]
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1932, "standing"), (1986, "standing")]
    assert segs[1]["state"]["description"] == "tulips added"


def test_reopening_after_fire_is_rebuilt_never_burnt():
    """De Adriaan 2002: context words ("70 years after fire") never set it."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1999, "event": "rebuilt", "verdict": "supported",
         "quote_span": "Rebuilding started April 1999.",
         "completed": True, "visible_change": ""},
        {"year": 2002, "event": "rebuilt", "verdict": "supported",
         "quote_span": "Rebuilt Adriaan reopened 23 April 2002, exactly 70 years "
                      "after fire, on original foundations.",
         "completed": True, "visible_change": "full windmill back on skyline"},
    ])
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1999, "under_construction"), (2002, "rebuilt")]


def test_re_erection_after_flood_is_rebuilt_never_ruin():
    """Kintai 1674: destruction stated plus rebuild is genuine, not a facelift."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1673, "event": "built", "verdict": "supported",
         "quote_span": "Built in 1673.", "completed": True, "visible_change": ""},
        {"year": 1674, "event": "rebuilt", "verdict": "supported",
         "quote_span": "The bridge was destroyed by a flood and was rebuilt in "
                      "1674 with improvements.",
         "completed": True, "visible_change": "bridge re-erected"},
    ])
    segs = research.build_timeline(events)
    assert [(s["from_year"], s["state"]["condition"]) for s in segs] == [
        (1673, "standing"), (1674, "rebuilt")]


def test_build_finished_and_lit_is_standing():
    """Rubjerg 1899: first lighting is operational completion, not 54 years on site."""
    from witness import research
    from witness.cli import timeline_events

    events = timeline_events([
        {"year": 1899, "event": "built", "verdict": "supported",
         "quote_span": "Construction began in 1899 on a lighthouse; light first "
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


def test_draft_scenes_carry_no_unverified_text():
    from witness.cli import draft_scenes

    made = kept_claim(1900, "rebuilt", "The tower was rebuilt.")
    made["quote_span"] = "The tower was rebuilt with a golden roof."
    made["visible_change"] = "Rebuilt with a golden roof."
    draft = draft_scenes([made])
    assert draft and draft[0]["from_year"] == 1900
    assert draft[0]["state"]["description"] == ""
    assert draft[0]["caption_lines"] == []


def test_run_job_emits_only_filmed_scenes(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import research as research_module

    _stub_job(monkeypatch)

    def bombed(respond, question):
        answer = _job_answer()
        answer["events"][0]["event"] = "bombed"
        answer["events"][0]["detail"] = "The mill was bombed in 1900."
        return answer

    monkeypatch.setattr(research_module, "ask_lifespan", bombed)
    seen = {"scenes": []}
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="Town", lang="en",
        decide=lambda found: True, no_cache=True, verify_with="meta",
        progress=None, quiet=True, out_dir=str(tmp_path / "out"),
        on_scene=lambda scene, number: seen["scenes"].append(scene))
    assert 1900 not in {s["from_year"] for s in seen["scenes"]}
    live = next(s for s in seen["scenes"] if s["from_year"] == 1920)
    assert live["state"]["description"] == "mill whole and white again"
    assert result["chosen"] and all(
        s["from_year"] != 1900 for s in result["chosen"])


def test_collect_era_files_skips_years_missing_from_the_film(tmp_path, monkeypatch):
    from witness import cli as cli_module

    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_stream"
    era_dir.mkdir(parents=True)
    (era_dir / "1944.png").write_bytes(b"fake-bytes")
    chosen = [{"from_year": 1900, "caption_lines": [],
               "caption_sentence": {"text": "I stood."}}]
    (out_dir / "research.json").write_text("{}")
    entries = [{"year": 1944, "verdict": "matches", "attempts": 1,
                "caption": ""}]
    files = cli_module.collect_era_files(out_dir, entries, chosen,
                                         "eras_stream")
    assert "1944" not in files


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


def test_report_and_save_stores_country_code(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from witness.cli import report_and_save

    monkeypatch.chdir(tmp_path)
    found = SimpleNamespace(name="Test Mill", kind="mill", qid="Q1",
                            articles={"en": "Test_Mill"},
                            country_code="dk")
    result = {"outcome": "too_little", "reason": "test", "verified": 0,
              "eras": 0, "good_sources": 0}
    slug = report_and_save(found, "en", ["en"], [], [], [], result,
                           {"total_s": 1.0}, "baseten", [], None)
    saved = json.loads((tmp_path / "out" / slug / "research.json").read_text())
    assert saved["object"]["country_code"] == "dk"


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
    passage = "https://a.example/mill\nThe mill burnt down."
    out = cli_module.caption_support_respond("I burnt down.", [passage])
    assert out["verdict"] == "supported"
    assert seen["votes"] == 3
    assert seen["passages"] == [passage]


def test_child_support_respond_uses_three_votes(monkeypatch):
    from witness import cli as cli_module

    seen = {}

    def fake_judge(respond, job, completion=True):
        seen.update(job)
        return {"verdict": "supported", "quote": "The mill burnt down.",
                "url": "https://a.example/mill"}

    monkeypatch.setattr(cli_module.verify, "judge_claim", fake_judge)
    passage = "https://a.example/mill\nThe mill burnt down."
    out = cli_module.child_support_respond("I burnt down.", [passage],
                                           1932, ["burnt"])
    assert out["verdict"] == "supported"
    assert seen["votes"] == 3
    assert seen["year"] == 1932
    assert seen["keywords"] == ["burnt"]


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


def anchor_claim():
    return {"year": 1900, "anchor": "build", "claim": "built in 1900",
            "event": "built", "quote_span": "", "date_text": "",
            "sources": ["https://en.wikipedia.org/wiki/X"]}


def test_verified_anchor_rejects_negated_planned_and_other_object(monkeypatch):
    from witness import cli as cli_module
    from witness.cli import confirm_build_anchor

    monkeypatch.setattr(cli_module.verify, "sentence_disputed",
                        lambda *a, **k: False)
    url = "https://en.wikipedia.org/wiki/X"
    for sentence in ("The tower was not built in 1900, despite popular claims.",
                     "The nearby church was built in 1900 by the same architect.",
                     "A tower was planned to be built in 1900 but never started."):
        assert confirm_build_anchor(
            anchor_claim(), {url: sentence + " More article text here."}) is None
    good = "The tower was built in 1900 by the town architect."
    assert confirm_build_anchor(
        anchor_claim(), {url: good + " More article text here."}) == 1900


def test_verified_anchor_rejects_a_disputed_sentence(monkeypatch):
    from witness import cli as cli_module
    from witness.cli import confirm_build_anchor

    monkeypatch.setattr(cli_module.verify, "sentence_disputed",
                        lambda *a, **k: True)
    url = "https://en.wikipedia.org/wiki/X"
    good = "The tower was built in 1900 by the town architect."
    assert confirm_build_anchor(
        anchor_claim(), {url: good + " More article text here."}) is None


def test_cmd_paint_records_per_era_seasons_from_photo_month(tmp_path, monkeypatch):
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1932, "verdict": "supported", "claim": "burnt"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Stands whole."},
             "caption_lines": []},
            {"from_year": 1932, "date_label": "23 April 1932",
             "state": {"condition": "ruin", "degree": "total",
                       "scope": "whole", "description": "Burnt down."},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": f"r-{prev_id or 'none'}"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), mode="parallel",
        paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: winter\nNone",
        photo_month=2)
    assert code == 0
    manifest = json.loads((out_dir / "paint_parallel.json").read_text())
    seasons = {entry["year"]: entry["season"] for entry in manifest["eras"]}
    assert seasons == {1850: "winter", 1932: "spring"}


def test_cmd_paint_counts_only_the_eras_it_painted(tmp_path, monkeypatch, capsys):
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "verdict": "supported", "claim": "stood"},
                   {"year": 1932, "verdict": "supported", "claim": "burnt"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Stands whole."},
             "caption_lines": []},
            {"from_year": 1932, "date_label": "1932",
             "state": {"condition": "ruin", "degree": "total",
                       "scope": "whole", "description": "Burnt down."},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)
    (out_dir / "paint_parallel.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": ""}]}))

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": f"r-{prev_id or 'none'}"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), mode="parallel", scenes="1932",
        paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: winter\nNone")
    assert code == 0
    assert "painted 1 of 1 eras" in capsys.readouterr().out


def test_cmd_paint_reads_country_code_for_era_seasons(tmp_path, monkeypatch):
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
        "object": {"name": "Test Light", "qid": "Q1", "lang": "en",
                   "municipality": "Test Town", "country_code": "dk"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 2019, "verdict": "supported", "claim": "moved"}],
        "scenes": [
            {"from_year": 2019, "date_label": "22 October 2019",
             "state": {"condition": "moved", "degree": "total",
                       "scope": "whole", "description": "Moved inland."},
             "caption_lines": []},
        ]}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(tiny)

    def fake_call(prompt, prev_id, photo_bytes=None):
        return {"image": tiny, "response_id": f"r-{prev_id or 'none'}"}

    code = cli_module.cmd_paint(
        "q1-test", str(photo), mode="parallel",
        paint_call=fake_call,
        check_call=lambda image, prompt: "MATCHES whole.",
        photo_call=lambda photo, prompt: "Season: winter\nNone",
        photo_month=6)
    assert code == 0
    manifest = json.loads((out_dir / "paint_parallel.json").read_text())
    assert manifest["eras"][0]["season"] == "autumn"


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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(photo), mode="parallel",
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
         "caption": "", "season": "summer",
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(photo), mode="chain",
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
            "q1-test", str(photo), mode="parallel",
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        rewrite_call=lambda adult, source, plain, gentle=False, stamp="": f"Little: {adult}",
        support_call=lambda line, source, *a: "supported")
    assert code == 0
    data = json.loads((out_dir / "research.json").read_text())
    lines = data["scenes"][0]["caption_lines"]
    assert lines[0]["child"] == "Little: in 1802 sold"
    assert lines[0]["child_verified"] is True
    assert lines[1]["child"] is None
    assert data["scenes"][0]["child_state"] == "Little: opened in 1779"




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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(photo), mode="parallel", tag="b1",
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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "evidence": {"claim": "opened in 1850",
                                              "url": "https://a.example/x",
                                              "quote": "The mill opened in 1850."}}},
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
    assert (film_dir / "era_1850.png").exists()
    assert Image.open(film_dir / "era_1850.png").format == "PNG"
    assert (film_dir / "era_1850.png").read_bytes() == (era_dir / "1850.png").read_bytes()
    assert (film_dir / "today.jpg").exists()
    assert (film_dir / "cutout.png").exists()
    film = json.loads((film_dir / "film.json").read_text())
    assert film["object"] == "Test Mill"
    assert film["today_line"] == "And here I stand today."
    assert film["today_sub"] == ""
    assert film["scenes"][0]["caption"][0] == "1850"


def render_both_setup(tmp_path):
    import io
    import json
    from PIL import Image

    out_dir = tmp_path / "out" / "q1-test"
    adult_dir = out_dir / "eras_parallel"
    child_dir = out_dir / "eras_parallel_child"
    adult_dir.mkdir(parents=True)
    child_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "red").save(buf, "PNG")
    adult = buf.getvalue()
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "blue").save(buf, "PNG")
    child = buf.getvalue()
    (adult_dir / "1850.png").write_bytes(adult)
    (child_dir / "1850.png").write_bytes(child)
    (out_dir / "paint_parallel.json").write_text(json.dumps(
        {"audience": "adult",
         "eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
    (out_dir / "paint_parallel_child.json").write_text(json.dumps(
        {"audience": "child",
         "eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "Little mill words."}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "child": {"text": "Little mill words."},
                                 "evidence": {"claim": "opened in 1850",
                                              "url": "https://a.example/x",
                                              "quote": "The mill opened in 1850."}}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(adult)
    return out_dir, str(photo), child


def test_cmd_render_builds_both_audiences_when_child_set_matches(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, child_bytes = render_both_setup(tmp_path)
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me")
    assert code == 0
    adult_film = json.loads((out_dir / "film" / "film.json").read_text())
    assert adult_film["audience"] == "adult"
    assert adult_film["sibling"] == "child/film.json"
    child_film = json.loads((out_dir / "film" / "child" / "film.json").read_text())
    assert child_film["audience"] == "child"
    assert child_film["sibling"] == "../film.json"
    assert child_film["scenes"][0]["caption"] == ["1850", "Little mill words."]
    assert (out_dir / "film" / "child" / "era_1850.png").read_bytes() == child_bytes
    assert (out_dir / "film" / "child" / "film.html").exists()


def test_cmd_render_marks_a_lone_film_without_sibling(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, _ = render_both_setup(tmp_path)
    (out_dir / "paint_parallel_child.json").unlink()
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me")
    assert code == 0
    adult_film = json.loads((out_dir / "film" / "film.json").read_text())
    assert adult_film["sibling"] is None
    assert not (out_dir / "film" / "child").exists()


def test_cmd_render_skips_child_film_when_a_year_is_missing(tmp_path, monkeypatch, capsys):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, _ = render_both_setup(tmp_path)
    (out_dir / "paint_parallel_child.json").write_text(json.dumps(
        {"audience": "child",
         "eras": [{"year": 1850, "verdict": "dropped", "attempts": 3,
                   "caption": "Little mill words."}]}))
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me")
    assert code == 0
    assert "children" in capsys.readouterr().out
    assert not (out_dir / "film" / "child").exists()
    adult_film = json.loads((out_dir / "film" / "film.json").read_text())
    assert adult_film["sibling"] is None


def test_cmd_render_adds_a_grounded_game_to_the_child_film(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, _ = render_both_setup(tmp_path)
    data = json.loads((out_dir / "research.json").read_text())
    extra = [(1900, "Taller."), (1950, "Repainted.")]
    for year, description in extra:
        data["claims"].append(
            {"year": year, "url": "https://a.example/x",
             "verdict": "supported", "claim": f"changed in {year}",
             "quote": f"It changed in {year}."})
        data["scenes"].append(
            {"from_year": year, "date_label": str(year),
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": description},
             "caption_lines": [],
             "caption_sentence": {"text": f"I changed in {year}.",
                                 "claim_year": year,
                                 "claim_url": "https://a.example/x",
                                 "child": {"text": f"Little change in {year}."},
                                 "evidence": {"claim": f"changed in {year}",
                                              "url": "https://a.example/x",
                                              "quote": f"It changed in {year}.",
                                              "sentence_url": "https://a.example/x"}}})
    (out_dir / "research.json").write_text(json.dumps(data))
    (out_dir / "spot.json").write_text(json.dumps(
        {"year": 1850,
         "differences": [{"change": "1850: Whole."},
                         {"change": "1900: Taller."},
                         {"change": "1950: Repainted."}]}))
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me")
    assert code == 0
    adult_film = json.loads((out_dir / "film" / "film.json").read_text())
    assert adult_film["spot"] is None
    child_film = json.loads((out_dir / "film" / "child" / "film.json").read_text())
    assert child_film["spot"] == "spot.html"
    page = (out_dir / "film" / "child" / "spot.html").read_text()
    assert "1850: Whole." in page


def test_cmd_render_drops_a_game_that_lost_its_grounding(tmp_path, monkeypatch, capsys):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, _ = render_both_setup(tmp_path)
    (out_dir / "spot.json").write_text(json.dumps(
        {"year": 1850,
         "differences": [{"text": f"Difference {n}.",
                          "change": "1850: Whole."} for n in (1, 2)]
         + [{"text": "A dragon.", "change": "1850: A dragon landed."}]}))
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me")
    assert code == 0
    assert "grounded" in capsys.readouterr().out
    child_film = json.loads((out_dir / "film" / "child" / "film.json").read_text())
    assert child_film["spot"] is None
    assert not (out_dir / "film" / "child" / "spot.html").exists()


def test_cmd_render_refuses_child_manifest_as_primary(tmp_path, monkeypatch, capsys):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, _ = render_both_setup(tmp_path)
    code = cli_module.cmd_render("q1-test", photo, photo_credit="me",
                                 era_dir="eras_parallel_child")
    assert code == 2
    assert "children" in capsys.readouterr().out


def spot_setup(tmp_path):
    import io
    import json
    from PIL import Image

    years = [1779, 1865, 1932, 2002]
    texts = {1779: "The mill stands whole with four sails.",
             1865: "The mill gained a brick base.",
             1932: "The mill burnt, only the base left.",
             2002: "The mill rebuilt with new sails."}
    out_dir = tmp_path / "out" / "q1-test"
    child_dir = out_dir / "eras_parallel_child"
    child_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "blue").save(buf, "PNG")
    for year in years:
        (child_dir / f"{year}.png").write_bytes(buf.getvalue())
    (out_dir / "paint_parallel_child.json").write_text(json.dumps(
        {"audience": "child",
         "eras": [{"year": year, "verdict": "matches", "attempts": 1,
                   "caption": f"Little words for {year}."}
                  for year in years]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": year, "url": "https://a.example/x",
                    "verdict": "supported", "claim": texts[year],
                    "quote": texts[year]} for year in years],
        "scenes": [
            {"from_year": year, "date_label": str(year),
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": texts[year]},
             "caption_lines": [],
             "caption_sentence": {"text": f"Adult words for {year}.",
                                 "claim_year": year,
                                 "claim_url": "https://a.example/x",
                                 "child": {"text": f"Little words for {year}."},
                                 "evidence": {"claim": texts[year],
                                              "url": "https://a.example/x",
                                              "quote": texts[year]}}}
            for year in years],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(buf.getvalue())
    return out_dir, str(photo), texts


def grounded_stub(texts):
    def vision(era_bytes, photo_bytes, prompt):
        assert era_bytes and photo_bytes
        for line in texts.values():
            assert line in prompt
        return [{"text": "The sails are gone.",
                 "change": f"1932: {texts[1932]}"},
                {"text": "The base is brick.",
                 "change": f"1865: {texts[1865]}"},
                {"text": "New sails again.",
                 "change": f"2002: {texts[2002]}"}]
    return vision


def test_cmd_spot_writes_a_grounded_game(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, texts = spot_setup(tmp_path)
    code = cli_module.cmd_spot("q1-test", photo,
                               vision_call=grounded_stub(texts))
    assert code == 0
    game = json.loads((out_dir / "spot.json").read_text())
    assert game["year"] == 1779
    assert [d["change"] for d in game["differences"]] == [
        f"1932: {texts[1932]}", f"1865: {texts[1865]}",
        f"2002: {texts[2002]}"]
    assert all(set(d) == {"change"} for d in game["differences"])


def test_cmd_spot_skips_when_too_little_is_verified(tmp_path, monkeypatch, capsys):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, texts = spot_setup(tmp_path)
    data = json.loads((out_dir / "research.json").read_text())
    data["scenes"] = data["scenes"][:2]
    data["claims"] = data["claims"][:2]
    (out_dir / "research.json").write_text(json.dumps(data))
    seen = []
    code = cli_module.cmd_spot(
        "q1-test", photo, vision_call=lambda e, p, pr: seen.append(pr))
    assert code == 0
    assert seen == []
    assert "too little" in capsys.readouterr().out
    assert not (out_dir / "spot.json").exists()


def test_cmd_spot_skips_when_vision_grounds_too_little(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, texts = spot_setup(tmp_path)
    code = cli_module.cmd_spot(
        "q1-test", photo,
        vision_call=lambda e, p, pr: [{"text": "A dragon.",
                                       "change": "1932: A dragon landed."}])
    assert code == 0
    assert "grounded" in capsys.readouterr().out
    assert not (out_dir / "spot.json").exists()


def test_childrens_calls_are_counted_on_the_job_ledger(monkeypatch):
    import io
    import json
    from types import SimpleNamespace
    from PIL import Image
    from witness import cli as cli_module
    from witness import models

    usage = {"prompt_tokens": 1000, "completion_tokens": 100,
             "total_tokens": 1100}
    calls = []

    def canned_text(text):
        return SimpleNamespace(
            usage=dict(usage),
            model_dump_json=lambda: json.dumps(
                {"output": [{"content": [{"type": "output_text",
                                          "text": text}]}]}))

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(("responses", kwargs))
            if kwargs.get("text", {}).get("format", {}).get("name") == "spot_differences":
                return canned_text(json.dumps({"differences": []}))
            return canned_text("Little mill words.")

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(("chat", kwargs))
            return {"choices": [{"message": {
                "content": json.dumps({
                    "verdict": "supported",
                    "quote": "The old mill stood whole in 1779.",
                    "url": "https://a.example/x",
                    "support": [{"url": "https://a.example/x",
                                 "supports": True,
                                 "quote": "The old mill stood whole in 1779."}]}),
                "reasoning_content": ""}}],
                "usage": dict(usage)}

    fake = SimpleNamespace(responses=FakeResponses(),
                           chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(cli_module, "_respond_for", lambda spec: fake)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    models.reset_usage()
    with models.job_ledger() as ledger:
        line = cli_module.child_rewrite_respond(
            "Adult words.", "https://a.example/x", plain=False)
        verdict = cli_module.child_support_respond(
            "The mill stood whole.",
            ["https://a.example/x\nThe old mill stood whole in 1779."])
        cli_module.spot_respond(buf.getvalue(), buf.getvalue(), "spot them")
    assert line == "Little mill words."
    assert verdict["verdict"] == "supported"
    assert [kind for kind, _ in calls] == ["responses", "chat", "chat",
                                           "responses"]
    assert ledger.calls == 4
    assert ledger.cost_usd > 0
    assert set(ledger.totals) == {"meta", "baseten"}
    models.reset_usage()


def test_cmd_spot_needs_childrens_paintings_first(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, photo, texts = spot_setup(tmp_path)
    (out_dir / "paint_parallel_child.json").unlink()
    code = cli_module.cmd_spot("q1-test", photo,
                               vision_call=grounded_stub(texts))
    assert code == 2
    assert "paint" in capsys.readouterr().out


def test_cmd_render_reports_refused_scenes(tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module
    from witness import segment as segment_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())
    (out_dir / "paint_parallel.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
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
        era_dir="eras_parallel", photo_credit="me",
        segment_call=lambda call_sam, path, subject: cutout)
    assert code == 0
    out, _ = capsys.readouterr()
    assert "1850" in out and "refused" in out
    film = json.loads((out_dir / "film" / "film.json").read_text())
    assert film["scenes"] == []


def test_cmd_paint_records_caption_and_warns_when_missing(tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    Image.new("RGB", (8, 8), "grey").save(tmp_path / "photo.jpg")
    (slug_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "claims": [{"year": 1850, "verdict": "supported", "claim": "opened in 1850"},
                   {"year": 1900, "verdict": "supported", "claim": "stood in 1900"}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x"}},
            {"from_year": 1900, "date_label": "1900",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": []},
        ],
    }))
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "grey").save(buf, "PNG")
    png = buf.getvalue()

    def call(prompt, prev_id, photo_bytes=None):
        return {"image": png, "response_id": "r1"}

    code = cli_module.cmd_paint(
        "q1-test", str(tmp_path / "photo.jpg"),
        paint_call=call, check_call=lambda image, p: "MATCHES whole.",
        photo_call=lambda photo_bytes, prompt: "summer")
    assert code == 0
    manifest = json.loads((slug_dir / "paint_parallel.json").read_text())
    by_year = {e["year"]: e for e in manifest["eras"]}
    assert by_year[1850]["caption"] == "I opened my doors."
    assert by_year[1900]["caption"] == ""
    out, _ = capsys.readouterr()
    assert "1900" in out and "no caption" in out


def test_cmd_render_refuses_caption_mismatch(tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module
    from witness import segment as segment_module

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out" / "q1-test"
    era_dir = out_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), "red").save(buf, "PNG")
    (era_dir / "1850.png").write_bytes(buf.getvalue())
    (out_dir / "paint_parallel.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my old doors."}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "evidence": {"claim": "opened in 1850",
                                              "url": "https://a.example/x",
                                              "quote": "The mill opened in 1850."}}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(buf.getvalue())
    cutout = segment_module.Cutout(
        (0, 0, 8, 8), 0.5, Image.new("L", (16, 24)),
        Image.new("RGBA", (16, 24), (1, 2, 3, 255)))

    code = cli_module.cmd_render(
        "q1-test", str(photo), subject="mill",
        era_dir="eras_parallel", photo_credit="me",
        segment_call=lambda call_sam, path, subject: cutout)
    assert code == 2
    out, _ = capsys.readouterr()
    assert "1850" in out and "caption" in out


def test_cmd_captions_rechecks_stale_paintings(tmp_path, monkeypatch, capsys):
    import io
    import json
    from PIL import Image
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    era_dir = slug_dir / "eras_parallel"
    era_dir.mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "grey").save(buf, "PNG")
    (era_dir / "1779.png").write_bytes(buf.getvalue())
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))
    (slug_dir / "paint_parallel.json").write_text(json.dumps(
        {"eras": [{"year": 1779, "verdict": "matches", "attempts": 1,
                   "file": "eras_parallel/1779.png",
                   "caption": "I opened my old doors."}]}))
    checked = []

    def check(image, prompt):
        checked.append(prompt)
        return "MATCHES whole mill."

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I opened my doors.",
        support_call=lambda sentence, passages, *a: "supported",
        check_call=check)
    assert code == 0
    assert len(checked) == 1
    assert "I opened my doors." in checked[0]
    manifest = json.loads((slug_dir / "paint_parallel.json").read_text())
    assert manifest["eras"][0]["caption"] == "I opened my doors."
    assert manifest["eras"][0]["verdict"] == "matches"


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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
    (out_dir / "research.json").write_text(json.dumps({
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "evidence": {"claim": "opened in 1850",
                                              "url": "https://a.example/x",
                                              "quote": "The mill opened in 1850."}}},
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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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


def test_capped_result_does_not_crash_film(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.setattr(cli_module, "run_job", lambda *a, **k: {
        "identified": True, "confirmed": True, "cached": False,
        "capped": True, "error": "daily spending cap reached"})
    code = cli_module.cmd_film("unused", yes=True,
                               out_dir=str(tmp_path / "out"))
    assert code == 2
    assert "cap" in capsys.readouterr().out


def test_cancelled_result_does_not_crash_film_or_research(
        tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.setattr(cli_module, "run_job", lambda *a, **k: {
        "identified": False, "confirmed": False, "cached": False,
        "cancelled": True, "error": "job cancelled"})
    assert cli_module.cmd_film("unused", yes=True,
                               out_dir=str(tmp_path / "out")) == 2
    assert cli_module.cmd_research("unused", yes=True,
                                   out_dir=str(tmp_path / "out")) == 2
    assert "cancelled" in capsys.readouterr().out


def test_reviewed_cache_asks_decide(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from witness import cli as cli_module
    from witness.cache import Cache

    _stub_job(monkeypatch)
    decisions = []
    cache = Cache(str(tmp_path / "cache"))
    cache.put_reviewed("Q1", "en", {"outcome": {"outcome": "short_film"}})
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"),
        decide=lambda found: decisions.append(found.name) or False,
        no_cache=False, cache=cache, verify_with="meta", progress=None,
        quiet=True, out_dir=str(tmp_path / "out"))
    assert decisions == ["Test Mill"]
    assert result["confirmed"] is False


def test_pre_cancelled_job_returns_cancelled(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    _stub_job(monkeypatch)
    control = models.JobControl()
    control.cancel()
    result = cli_module.run_job(
        str(tmp_path / "photo.jpg"), decide=lambda found: True,
        no_cache=True, verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"), control=control)
    assert result["cancelled"] is True
    assert result["confirmed"] is False


def test_absent_decide_is_not_yes(tmp_path, monkeypatch):
    import pytest
    from witness import cli as cli_module

    _stub_job(monkeypatch)
    with pytest.raises(ValueError):
        cli_module.run_job(
            str(tmp_path / "photo.jpg"), no_cache=True,
            verify_with="meta", progress=None, quiet=True,
            out_dir=str(tmp_path / "out"))


def test_run_job_admits_before_paid_identify(tmp_path, monkeypatch):
    from witness import cli as cli_module
    from witness import models

    seen = []
    _stub_job(monkeypatch)
    monkeypatch.setattr(cli_module.identify, "identify",
                        lambda *a, **k: seen.append(1) or _job_found())
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0,
                              daily_films=1, visitor_films=1)
    try:
        first = cli_module.run_job(
            str(tmp_path / "photo.jpg"), decide=lambda found: True,
            no_cache=True, verify_with="meta", progress=None, quiet=True,
            out_dir=str(tmp_path / "out"), visitor="visitor-a")
        assert first["confirmed"] is True
        result = cli_module.run_job(
            str(tmp_path / "photo.jpg"), decide=lambda found: True,
            no_cache=True, verify_with="meta", progress=None, quiet=True,
            out_dir=str(tmp_path / "out"), visitor="visitor-a")
        assert result["confirmed"] is False
        assert result["error_kind"] == "quota"
        assert len(seen) == 1  # the refused job never reached identify
    finally:
        models.configure_spending(None)


def test_film_save_records_real_job_cost(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    from witness import cli as cli_module
    from witness import models

    models.reset_usage()

    @models.with_job_ledger
    def fake_run(*args, **kwargs):
        models.current_ledger().note("meta", "muse-spark-1.3",
                                    {"input_tokens": 1000})
        return {"identified": True, "confirmed": True, "cached": False,
                "slug": "q1-test", "found": SimpleNamespace(name="Mill"),
                "order": [], "kept": [], "timeline": [], "chosen": [],
                "result": {"outcome": "too_little"}, "timings": {"total_s": 0},
                "failures": [], "comparison": None,
                "tokens": models.usage_totals(),
                "cost_usd": models.current_cost_usd()}

    saved = {}

    def save(*args, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(cli_module, "run_job", fake_run)
    monkeypatch.setattr(cli_module, "report_and_save", save)
    assert cli_module.cmd_film("unused", yes=True,
                               out_dir=str(tmp_path / "out")) == 0
    assert saved["cost_usd"] == pytest.approx(1000 / 1e6 * 1.25)
    assert saved["cost_usd"] > 0


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


def test_stream_scene_kwargs_gives_dated_eras_their_season():
    from witness import cli as cli_module

    report = {"season": "winter", "elements": []}
    kwargs = cli_module.stream_scene_kwargs(
        report, [], {"from_year": 1932, "date_label": "23 April 1932"},
        photo_month=1)
    assert kwargs["season"] == "spring"


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
        "object": {"name": "Test Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"year": 1850, "url": "https://a.example/x",
                    "verdict": "supported", "claim": "opened in 1850",
                    "quote": "The mill opened in 1850."}],
        "scenes": [
            {"from_year": 1850, "date_label": "1850",
             "state": {"condition": "standing", "degree": "total",
                       "scope": "whole", "description": "Whole."},
             "caption_lines": [],
             "caption_sentence": {"text": "I opened my doors.",
                                 "claim_year": 1850,
                                 "claim_url": "https://a.example/x",
                                 "evidence": {"claim": "opened in 1850",
                                              "url": "https://a.example/x",
                                              "quote": "The mill opened in 1850."}}},
        ],
        "timeline": [], "timings": {}}))
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (24, 16), "blue").save(photo)
    return out_dir, photo


def test_render_with_corrupt_photo_refuses(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    out_dir, _photo = _render_fixture(tmp_path)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image" * 4)
    code = cli_module.cmd_render("q1-test", str(bad),
                                 era_dir="eras_parallel_b1")
    assert code == 2
    assert "bad photo" in capsys.readouterr().out


def test_film_with_corrupt_photo_refuses(tmp_path, monkeypatch, capsys):
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image" * 4)
    code = cli_module.cmd_film(str(bad), yes=True, paint_eras=True,
                               out_dir=str(tmp_path / "out"))
    assert code == 2
    assert "bad photo" in capsys.readouterr().out


def test_job_dirs_are_random_and_private(tmp_path):
    import os
    from witness import cli as cli_module

    first = cli_module.job_dir(tmp_path)
    second = cli_module.job_dir(tmp_path)
    assert first != second
    assert oct(os.stat(first).st_mode & 0o777) == "0o700"


def test_render_uses_separate_knowledge_cache(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module
    from witness.cache import Cache

    monkeypatch.chdir(tmp_path)
    out_dir, photo = _render_fixture(tmp_path)
    (out_dir / "paint_parallel_b1.json").write_text(json.dumps(
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
    research_path = out_dir / "research.json"
    research = json.loads(research_path.read_text())
    research["claims"] = [
        {"year": 1850, "verdict": "supported", "claim": "opened in 1850",
         "url": "https://a.example/x",
         "quote": "I opened my doors to the town that spring."}]
    research_path.write_text(json.dumps(research))
    separate = Cache(tmp_path / "knowledge")
    separate.put("https://a.example/x",
                 "I opened my doors to the town that spring. In 1850, witnesses agree.")
    code = cli_module.cmd_render("q1-test", str(photo),
                                 era_dir="eras_parallel_b1",
                                 cache=separate)
    assert code == 0
    film = json.loads((out_dir / "film" / "film.json").read_text())
    assert [entry["url"] for entry in film["sources"]] == ["https://a.example/x"]


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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."},
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


def test_judge_batch_uses_wiring_completion(monkeypatch):
    import json as _json

    from witness import cli as cli_module

    monkeypatch.setattr(cli_module.verify, "sentence_disputed",
                        lambda *a, **k: False)
    seen = []

    quote = "The old mill was built in 1850 here by the river bank."

    def support(prompt):
        seen.append("support")
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps(
                 {"verdict": "supported", "quote": quote,
                  "url": "https://other.example/x",
                  "support": [{"url": "https://other.example/x",
                               "supports": True,
                               "quote": quote}]}),
             "annotations": []}]}]}

    def completion(prompt):
        seen.append("completion")
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": _json.dumps({"completed": True, "quote": quote}),
             "annotations": []}]}]}

    wiring = {"support": support, "completion": completion, "workers": 1}
    job = {"claim": "Built in 1850.", "event": "built",
           "detail": "Built in 1850.", "year": 1850, "date_text": "in 1850",
           "keywords": ["built"],
           "passages": [f"https://en.wikipedia.org/wiki/X\n{quote}"],
           "urls": ["https://en.wikipedia.org/wiki/X"], "votes": 1,
           "anchor": None, "claim_index": 0}
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
        candidates=(), country_code="NL", municipality="Canon Town")


def _job_first():
    return {"facts": {"facts": []},
            "claims": [{"year": 1850, "event": "built", "kind": "object",
                        "claim": "Built in 1850.",
                        "quote_span": "built in 1850",
                        "date_text": "in 1850",
                        "visible_change": "new mill whole and white",
                        "sources": [_JOB_WIKI], "anchor": "build"}],
            "build_anchor_year": 1850}


def _job_answer():
    return {"events": [{"year": 1900, "event": "damaged",
                        "detail": "roof holed in a storm",
                        "date_text": "in 1900",
                        "visible_change": "roof holed open to the sky"},
                       {"year": 1920, "event": "rebuilt",
                        "detail": "rebuilt after the storm",
                        "date_text": "in 1920",
                        "visible_change": "mill whole and white again"}],
            "sources": [],
            "citations": [{"url": _JOB_WIKI, "title": "Test Mill"}],
            "snippets": []}


def _answered(obj):
    import json as _json

    return {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": _json.dumps(obj),
         "annotations": []}]}]}


_JOB_SENTENCES = {
    "1850": "The test mill was built in 1850 by the river bank.",
    "1900": "The roof was holed in a great storm in 1900.",
    "1920": "The mill was rebuilt in 1920 after the great storm.",
}


def _job_respond(prompt):
    lines = prompt.split("\n")
    claim_line = lines[1] if len(lines) > 1 else prompt
    year = next((y for y in _JOB_SENTENCES if y in claim_line), "1920")
    if prompt.startswith("Claim:\n"):
        return _answered({"completed": True, "quote": _JOB_SENTENCES[year]})
    return _answered(
        {"verdict": "supported", "quote": _JOB_SENTENCES[year],
         "url": _JOB_WIKI,
         "support": [{"url": _JOB_WIKI, "supports": True,
                      "quote": _JOB_SENTENCES[year]}]})


class _JobTexts:
    def __init__(self, cache=None, progress=None):
        self.texts = {_JOB_WIKI: " ".join(_JOB_SENTENCES.values())}
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
    # Stub pages are readable and undisputed; unreadable pages count as
    # disputed (test_sentence_disputed_treats_an_unreadable_page_as_disputed).
    monkeypatch.setattr(cli_module.verify, "sentence_disputed",
                        lambda *a, **k: False)


def test_research_question_uses_municipality_never_typed_place(tmp_path, monkeypatch):
    from witness import cli as cli_module

    calls = []
    _stub_job(monkeypatch, calls=calls)
    cli_module.run_job(
        str(tmp_path / "photo.jpg"), place="SYNTHETIC_PRIVATE_PLACE",
        lang="en", decide=lambda found: True, no_cache=True,
        verify_with="meta", progress=None, quiet=True,
        out_dir=str(tmp_path / "out"))
    assert len(calls) == 1
    assert "Canon Town" in calls[0]
    assert "SYNTHETIC_PRIVATE_PLACE" not in calls[0]


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
        {"eras": [{"year": 1850, "verdict": "matches", "attempts": 1,
                   "caption": "I opened my doors."}]}))
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



def _caption_research():
    return {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        support_call=lambda sentence, quote, *a: "supported")
    assert code == 0
    assert calls == [(1779, False)]
    saved = json.loads((slug_dir / "research.json").read_text())
    first, second = saved["scenes"]
    assert first["caption_sentence"] == {
        "text": "I opened my doors to the town.",
        "claim_year": 1779, "claim_url": "https://a.example/x",
        "evidence": {"claim": "opened in 1779",
                     "url": "https://a.example/x",
                     "quote": "The mill opened in 1779.",
                     "sentence_url": "https://a.example/x"}}
    assert "caption_sentence" not in second


def test_cmd_captions_stores_the_supporting_sentence(tmp_path, monkeypatch, capsys):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))

    def support(sentence, passages, year, keywords):
        return {"verdict": "supported",
                "quote": "The doors opened to the town in 1779.",
                "url": "https://a.example/z"}

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I opened my doors.",
        support_call=support)
    assert code == 0
    saved = json.loads((slug_dir / "research.json").read_text())
    assert saved["scenes"][0]["caption_sentence"]["evidence"] == {
        "claim": "opened in 1779", "url": "https://a.example/x",
        "quote": "The doors opened to the town in 1779.",
        "sentence_url": "https://a.example/z"}


def test_cmd_captions_judges_sentences_with_object_context(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    (slug_dir / "research.json").write_text(json.dumps(_caption_research()))
    seen = []

    def support(sentence, passages, *a):
        seen.append(sentence)
        return "supported"

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I opened my doors.",
        support_call=support)
    assert code == 0
    assert seen == ["In 1779, Mill: I opened my doors."]


def test_cmd_captions_judges_against_cached_article_text(tmp_path, monkeypatch):
    import json
    from witness import cli as cli_module
    from witness.cache import Cache

    monkeypatch.chdir(tmp_path)
    slug_dir = tmp_path / "out" / "q1-test"
    slug_dir.mkdir(parents=True)
    data = _caption_research()
    data["claims"][0]["url"] = "https://rich-captions.example/mill"
    (slug_dir / "research.json").write_text(json.dumps(data))
    cache = Cache(tmp_path / "cache")
    cache.put("https://rich-captions.example/mill",
              "The old mill stood by the river for many years.\n\n"
              "The mill opened in 1779 after years of building work.")
    seen = []

    def support(sentence, passages, *a):
        seen.extend(passages)
        return "supported"

    code = cli_module.cmd_captions(
        "q1-test",
        rewrite_call=lambda detail, quote, year, plain, stamp="": "I opened my doors.",
        support_call=support, cache=cache)
    assert code == 0
    assert any("years of building work" in p for p in seen)


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
        support_call=lambda sentence, quote, *a: "supported")
    assert code == 2
    out, _ = capsys.readouterr()
    assert "spending cap" in out
    assert (slug_dir / "research.json").exists()



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
        support_call=lambda sentence, quote, *a: "supported")
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
        support_call=lambda sentence, quote, *a: "supported")
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
        "object": {"name": "Mill", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(tmp_path / "photo.jpg"), tag="b1",
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
        "object": {"name": "Oak", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(tmp_path / "photo.jpg"),
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
        "object": {"name": "Oak", "qid": "Q1", "lang": "en", "municipality": "Test Town"},
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
        "q1-test", str(tmp_path / "photo.jpg"),
        paint_call=call, check_call=lambda image, p: "MATCHES whole.",
        photo_call=lambda photo_bytes, prompt: "summer")
    assert code == 0
    assert painted == [False]
    assert not (slug_dir / "eras_parallel" / "1970.png").exists()
    manifest = json.loads((slug_dir / "paint_parallel.json").read_text())
    assert {e["year"]: e["verdict"] for e in manifest["eras"]} == {
        1790: "matches", 1970: "skipped"}


def test_pre_admitted_run_job_skips_admission(tmp_path, monkeypatch):
    import pytest

    import witness.cli as cli_module
    from witness import models

    class Recording:
        def __init__(self):
            self.admitted = []

        def admit(self, visitor, extra=None):
            self.admitted.append((visitor, extra))

    def boom(verify_with):
        raise RuntimeError("stop after admission")

    monkeypatch.setattr(cli_module, "verify_wiring", boom)
    rec = Recording()
    models.configure_spending(authority=rec)
    try:
        with pytest.raises(RuntimeError):
            cli_module.run_job(str(tmp_path / "p.jpg"), decide=lambda found: True,
                               no_cache=True, visitor="web-vid")
        assert rec.admitted == [("web-vid", None)]
        with pytest.raises(RuntimeError):
            cli_module.run_job(str(tmp_path / "p.jpg"), decide=lambda found: True,
                               no_cache=True, visitor="web-vid",
                               pre_admitted=True)
        assert rec.admitted == [("web-vid", None)]
    finally:
        models.configure_spending(None)
