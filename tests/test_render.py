"""Step 7: the renderer builds a live film page. No live calls."""

import json
from pathlib import Path

import pytest

from witness.render import builder


def scene(year, condition="standing", description="", lines=(), sentence=None,
            claim_year=None, claim_url="https://a.example/x"):
    made = {"from_year": year, "date_label": str(year),
            "state": {"condition": condition, "degree": "total",
                      "scope": "whole", "description": description},
            "caption_lines": [{"year": year, "line": line,
                               "url": "https://nl.wikipedia.org/wiki/X"}
                              for line in lines]}
    if sentence is not None:
        made["caption_sentence"] = {
            "text": sentence,
            "claim_year": year if claim_year is None else claim_year,
            "claim_url": claim_url,
            "evidence": {"claim": f"something happened in {year}",
                         "url": claim_url,
                         "quote": f"It happened in {year}."}}
    return made


def claims_for(scenes):
    return [{"year": s["caption_sentence"]["claim_year"],
             "url": s["caption_sentence"]["claim_url"],
             "verdict": "supported",
             "claim": s["caption_sentence"]["evidence"]["claim"],
             "quote": s["caption_sentence"]["evidence"]["quote"]}
            for s in scenes if "caption_sentence" in s]


def test_timeline_gives_every_part_its_seconds():
    scenes = [scene(1779, sentence="I opened."),
              scene(1865, sentence="I ground.")]
    plan = builder.build_timeline(
        scenes, {"1779": "e/1779.png", "1865": "e/1865.png"},
        claims_for(scenes))
    kinds = [(seg["kind"], seg["start"], seg["end"]) for seg in plan]
    assert kinds[0][0] == "title" and kinds[0][1] == 0
    assert kinds[1][0] == "anchor"
    assert [k for k, _, _ in kinds].count("era") == 2
    assert kinds[-2][0] == "today" and kinds[-1][0] == "end"
    for (_, start, end), (_, next_start, _) in zip(kinds, kinds[1:]):
        assert end == next_start
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert all(seg["end"] - seg["start"] == 7 for seg in eras)


def test_timeline_skips_eras_without_paintings():
    scenes = [scene(1779, sentence="I opened."),
              scene(1865, sentence="I ground.")]
    plan = builder.build_timeline(
        scenes, {"1865": "e/1865.png"}, claims_for(scenes))
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1865]


def test_timeline_skips_eras_without_written_sentences():
    scenes = [scene(1779, sentence="I opened."), scene(1865)]
    plan = builder.build_timeline(
        scenes, {"1779": "e/1779.png", "1865": "e/1865.png"},
        claims_for(scenes))
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1779]


def age_scene():
    made = scene(1026)
    made["date_label"] = "about 800 to 1,200 years old"
    return made


def test_filmable_refuses_a_caption_from_another_year():
    kept = scene(1900, sentence="I stood.")
    moved = scene(2000, sentence="I stood.")
    moved["caption_sentence"]["claim_year"] = 1900
    moved["caption_sentence"]["evidence"] = dict(
        kept["caption_sentence"]["evidence"])
    assert builder.filmable(moved, claims_for([kept])) is False
    assert builder.filmable(kept, claims_for([kept])) is True


def test_timeline_is_empty_without_filmable_eras():
    scenes = [scene(1779, sentence="I opened.")]
    assert builder.build_timeline(scenes, {}, claims_for(scenes)) == []


def test_timeline_never_films_an_age_range():
    scenes = [age_scene(), scene(1790, sentence="I was renamed.")]
    plan = builder.build_timeline(
        scenes, {"1026": "e/1026.png", "1790": "e/1790.png"},
        claims_for(scenes))
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1790]


def test_anchor_card_for_age_range_and_for_year():
    assert builder.anchor_card(age_scene()) == {
        "line": "My story starts",
        "label": "about 800 to 1,200 years ago."}
    built = scene(1899, sentence="My construction began.")
    claims = claims_for([built])
    claims[0]["event"] = "built"
    assert builder.anchor_card(built, claims) == {
        "line": "My story starts in", "label": "1899."}


def test_anchor_card_claims_the_start_only_for_a_beginning():
    """Rosslyn, 4 Nov: the first filmed fact was a 1736 restoration and
    the card said "My story starts in 1736." for a chapel founded in
    the 1450s. Only a checked build, opening or founding (or Wikidata's
    build date) may say the story starts there; any other first fact is
    named as the first checked date."""
    def card(event, anchor=None):
        made = scene(1736, sentence="Something happened to me.")
        claims = claims_for([made])
        if event is not None:
            claims[0]["event"] = event
        if anchor is not None:
            claims[0]["anchor"] = anchor
        return builder.anchor_card(made, claims)

    for event in ("built", "Constructed", "erected", "completed", "opened",
                  "founded", "planted"):
        assert card(event)["line"] == "My story starts in", event
    assert card("opened", anchor="build")["line"] == "My story starts in"
    for event in ("restored", "repurposed", "damaged", "burnt", "rebuilt",
                  "extended", "moved", None):
        assert card(event) == {"line": "My first checked\u00a0date:",
                               "label": "1736."}, event
    assert card(None, anchor="build")["line"] == "My story starts in"
    # The fact must be the one the caption cites, not any claim that year.
    made = scene(1736, sentence="I was glazed.")
    claims = claims_for([made]) + [{"year": 1736, "url": "https://b.example/y",
                                    "verdict": "supported", "event": "built",
                                    "claim": "built in 1736", "quote": "Built 1736."}]
    claims[0]["event"] = "restored"
    assert builder.anchor_card(made, claims)["line"] == "My first checked\u00a0date:"
    # No claims given: nothing proves a beginning.
    assert builder.anchor_card(made)["line"] == "My first checked\u00a0date:"


def test_write_film_starts_the_story_on_a_checked_build_fact(tmp_path):
    built = scene(1899, sentence="My construction began.")
    claims = claims_for([built])
    claims[0]["event"] = "built"
    research = {
        "object": {"name": "Light", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims,
        "scenes": [built], "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1899": "e/1899.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert film["anchor"] == {"line": "My story starts in", "label": "1899."}


def test_anchor_card_never_shows_a_computed_sort_year():
    made = scene(1026)
    made["date_label"] = "around a thousand years ago"
    card = builder.anchor_card(made)
    assert card["label"] != "1026"
    assert "thousand years ago" in card["label"]


def test_write_film_anchors_on_the_first_filmed_scene(tmp_path):
    dropped = scene(1779, sentence="I opened.")
    kept = scene(1932, sentence="I burnt down.")
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for([kept]),
        "scenes": [dropped, kept],
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research,
                             {"1779": "e/1779.png", "1932": "e/1932.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    # Burning down is not where a mill's story starts.
    assert film["anchor"] == {"line": "My first checked\u00a0date:",
                             "label": "1932."}


def test_write_film_carries_anchor_and_skips_age_scene(tmp_path):
    scenes = [age_scene(), scene(1790, sentence="I was renamed.")]
    research = {
        "object": {"name": "Oak", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research,
                             {"1026": "e/1026.png", "1790": "e/1790.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert [entry["year"] for entry in film["scenes"]] == [1790]
    # Major Oak: renamed in 1790 is not where a tree's story starts.
    assert film["anchor"] == {"line": "My first checked\u00a0date:",
                             "label": "1790."}


def test_caption_is_a_date_stamp_and_one_sentence():
    stamp, sentence = builder.caption_for(
        scene(1779, "standing", "opened in 1779",
              sentence="I opened my doors to the town."))
    assert stamp == "1779"
    assert sentence == "I opened my doors to the town."
    stamped = scene(1932)
    stamped["date_label"] = "23 April 1932"
    stamp, _ = builder.caption_for(stamped)
    assert stamp == "1932"


def test_stamp_shows_full_date_only_from_quote():
    dated = scene(1932, sentence="I burnt down.")
    dated["date_label"] = "23 April 1932"
    dated["caption_sentence"]["evidence"]["quote"] = (
        "On the evening of April 23, 1932 the windmill burnt down.")
    stamp, _ = builder.caption_for(dated)
    assert stamp == "23 April 1932"
    bare = scene(1900, sentence="I stood.")
    bare["date_label"] = "1 April 1900"
    bare["caption_sentence"]["evidence"]["quote"] = "It happened in 1900."
    stamp, _ = builder.caption_for(bare)
    assert stamp == "1900"
    season = scene(2016, sentence="I got a new stair.")
    season["date_label"] = "spring 2016"
    season["caption_sentence"]["evidence"]["quote"] = (
        "The staircase was renewed in 2016.")
    stamp, _ = builder.caption_for(season)
    assert stamp == "2016"


def test_stamp_never_combines_two_dates_into_one():
    mixed = scene(1900, sentence="I stood.")
    mixed["date_label"] = "1 April 1900"
    mixed["caption_sentence"]["evidence"]["quote"] = (
        "The tower opened on 1 April 1899. It was rebuilt on 2 May 1900.")
    stamp, _ = builder.caption_for(mixed)
    assert stamp == "1900"


def test_stamp_rejects_a_label_that_is_not_just_a_date():
    labelled = scene(1899, sentence="My construction began.")
    labelled["date_label"] = "1899; first lit 27 December 1900"
    labelled["caption_sentence"]["evidence"]["quote"] = (
        "The lighthouse was first lit on 27 December 1900.")
    stamp, _ = builder.caption_for(labelled)
    assert stamp == "1899"


def test_stamp_keeps_a_quoted_approximate_year():
    assert builder.stamp_for(
        "around 1900", 1900,
        "The tower was built around 1900.") == "around 1900"
    assert builder.stamp_for("around 1900", 1900, "It happened.") == "1900"
    qual = scene(1900, sentence="I stood.")
    qual["date_label"] = "around 1900"
    qual["caption_sentence"]["evidence"]["quote"] = (
        "The tower was built around 1900.")
    assert builder.caption_for(qual)[0] == "around 1900"
    assert builder.anchor_card(qual)["label"] == "around 1900."


def test_stamp_matches_complete_date_spans_only():
    assert builder.stamp_for(
        "1 April 1900", 1900,
        "The tower opened on 11 April 1900.") == "1900"
    assert builder.stamp_for(
        "1 April 1900", 1900,
        "The tower opened on 1 April 1900.") == "1 April 1900"


def test_anchor_card_uses_the_same_stamp_rule():
    first = scene(1900, sentence="I stood.")
    first["date_label"] = "1 April 1900"
    first["caption_sentence"]["evidence"]["quote"] = (
        "The tower opened on 1 April 1899. It was rebuilt on 2 May 1900.")
    assert builder.anchor_card(first)["label"] == "1900."
    dated = scene(1932, sentence="I burnt down.")
    dated["date_label"] = "23 April 1932"
    dated["caption_sentence"]["evidence"]["quote"] = (
        "On the evening of April 23, 1932 the windmill burnt down.")
    assert builder.anchor_card(dated)["label"] == "23 April 1932."
    labelled = scene(1899, sentence="My construction began.")
    labelled["date_label"] = "1899; first lit 27 December 1900"
    labelled["caption_sentence"]["evidence"]["quote"] = (
        "The lighthouse was first lit on 27 December 1900.")
    assert builder.anchor_card(labelled)["label"] == "1899."


def child_scene(year, line):
    made = scene(year, sentence=f"Adult words for {year}.")
    made["caption_sentence"]["child"] = {"text": line}
    return made


def test_child_caption_reads_the_childrens_sentence():
    stamp, sentence = builder.caption_for(
        child_scene(1779, "Little mill words."), audience="child")
    assert stamp == "1779"
    assert sentence == "Little mill words."


def test_child_caption_is_empty_without_a_childrens_sentence():
    stamp, sentence = builder.caption_for(
        scene(1779, sentence="Adult words."), audience="child")
    assert sentence == ""


def test_adult_caption_ignores_the_childrens_sentence():
    stamp, sentence = builder.caption_for(child_scene(1779, "Little mill words."))
    assert sentence == "Adult words for 1779."


def test_refusal_matches_the_claim_by_its_text():
    made = scene(1932, sentence="I burnt down.")
    made["caption_sentence"]["evidence"]["claim"] = "second thing"
    made["caption_sentence"]["evidence"]["quote"] = "The sentence that supported it."
    claims = [
        {"year": 1932, "url": "https://a.example/x", "verdict": "supported",
         "claim": "first thing", "quote": "First quote here."},
        {"year": 1932, "url": "https://a.example/x", "verdict": "supported",
         "claim": "second thing", "quote": "Second quote here."},
    ]
    assert builder.refusal_reason(made, claims) is None
    made["caption_sentence"]["evidence"]["claim"] = "renamed afterwards"
    assert (builder.refusal_reason(made, claims)
            == "its claim changed since the caption was written")


def test_refusal_checks_every_matching_claim():
    shared = "In 1900 the mill received new sails and a new cap from the town."
    made = scene(1900, sentence="I got new sails.")
    made["caption_sentence"]["evidence"]["claim"] = "Old claim the caption was written from"
    other = {"year": 1900, "url": "https://a.example/x", "verdict": "supported",
             "claim": "A different claim on the same sentence", "quote": shared}
    stale = {"year": 1900, "url": "https://a.example/x", "verdict": "unsupported",
             "claim": "Old claim the caption was written from", "quote": shared}
    assert builder.refusal_reason(made, [other, stale]) == "its claim is no longer supported"
    renamed = {"year": 1900, "url": "https://a.example/x", "verdict": "supported",
               "claim": "Totally rewritten claim text", "quote": shared}
    assert builder.filmable(made, [renamed]) is False


def test_child_film_refuses_a_scene_without_a_childrens_sentence():
    scenes = [child_scene(1779, "Little mill words."),
              scene(1865, sentence="Adult words.")]
    claims = claims_for(scenes)
    assert builder.refusal_reason(scenes[0], claims, audience="child") is None
    assert (builder.refusal_reason(scenes[1], claims, audience="child")
            == "no children's sentence")
    assert builder.refusal_reason(scenes[1], claims) is None


def test_child_film_keeps_the_adult_evidence_rule():
    made = child_scene(1779, "Little mill words.")
    made["caption_sentence"]["evidence"]["claim"] = "Changed afterwards."
    claims = claims_for([scene(1779, sentence="Adult words for 1779.")])
    assert (builder.refusal_reason(made, claims, audience="child")
            == "its claim changed since the caption was written")


def test_child_timeline_skips_scenes_without_childrens_sentences():
    scenes = [child_scene(1779, "Little mill words."),
              scene(1865, sentence="Adult words.")]
    plan = builder.build_timeline(
        scenes, {"1779": "e/1779.png", "1865": "e/1865.png"},
        claims_for(scenes), audience="child")
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1779]
    assert eras[0]["caption"] == ["1779", "Little mill words."]


def test_rendered_pair_switch_round_trips_through_served_routes(tmp_path):
    import re
    import shutil
    from urllib.parse import urljoin

    from fastapi.testclient import TestClient
    from PIL import Image

    from witness import webapp

    era = tmp_path / "era_1850.png"
    Image.new("RGB", (16, 24), "red").save(era)
    scenes = [child_scene(1850, "Little mill words.")]
    research = {"object": {"name": "Mill", "qid": "Q1", "lang": "en"},
                "outcome": {"outcome": "full_film"},
                "claims": claims_for(scenes), "scenes": scenes,
                "timeline": [], "timings": {}}
    job = tmp_path / "job"
    builder.write_film(job, research, {"1850": "era_1850.png"},
                       photo="today.jpg", photo_credit="me",
                       era_files={"1850": str(era)},
                       sibling="child/film.json")
    builder.write_film(job, research, {"1850": "era_1850.png"},
                       photo="today.jpg", photo_credit="me",
                       era_files={"1850": str(era)},
                       folder="film/child", audience="child",
                       sibling="../film.json")
    shutil.copytree(job / "film", tmp_path / "examples" / "mill")
    deps = webapp.WebDeps(store=webapp.MemoryStore(), authority=None,
                          runner=lambda ref: None,
                          jobs_root=tmp_path / "jobs",
                          examples_root=tmp_path / "examples",
                          examples=[{"slug": "mill", "name": "Mill"}])
    client = TestClient(webapp.create_app(deps))
    adult = client.get("/examples/mill/")
    assert adult.status_code == 200
    payload = json.loads(re.search(
        r'<script id="film-data" type="application/json">(.*?)</script>',
        adult.text, re.S).group(1))
    assert payload["sibling_page"] == "child/film.html"
    child_url = urljoin("https://served.invalid/examples/mill/",
                        payload["sibling_page"])
    assert "undefined" not in child_url
    child = client.get("/examples/mill/child/film.html")
    assert child.status_code == 200
    back = json.loads(re.search(
        r'<script id="film-data" type="application/json">(.*?)</script>',
        child.text, re.S).group(1))
    assert back["sibling_page"] == "../film.html"
    assert urljoin(child_url, back["sibling_page"]).endswith(
        "/examples/mill/film.html")
    assert client.get("/examples/mill/film.html").status_code == 200


def test_write_film_builds_a_sibling_child_film(tmp_path):
    from PIL import Image

    adult_era = tmp_path / "adult_1850.png"
    Image.new("RGB", (16, 24), "red").save(adult_era)
    child_era = tmp_path / "child_1850.png"
    Image.new("RGB", (16, 24), "blue").save(child_era)
    scenes = [child_scene(1850, "Little mill words.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    adult = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                               photo="today.jpg", photo_credit="me",
                               era_files={"1850": str(adult_era)},
                               sibling="child/film.json")
    child = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                               photo="today.jpg", photo_credit="me",
                               era_files={"1850": str(child_era)},
                               folder="film/child", audience="child",
                               sibling="../film.json")
    assert adult == tmp_path / "film"
    assert child == tmp_path / "film" / "child"
    adult_film = json.loads((adult / "film.json").read_text())
    child_film = json.loads((child / "film.json").read_text())
    assert adult_film["audience"] == "adult"
    assert adult_film["sibling"] == "child/film.json"
    assert child_film["audience"] == "child"
    assert child_film["sibling"] == "../film.json"
    from urllib.parse import urljoin

    adult_page = "https://example.org/film/id/cap/film.html"
    child_page = urljoin(adult_page, adult_film["sibling_page"])
    assert child_page.endswith("/film/id/cap/child/film.html")
    assert urljoin(child_page, child_film["sibling_page"]) == adult_page
    assert urljoin(child_page, "today.jpg").endswith("/cap/child/today.jpg")
    assert child_film["scenes"][0]["caption"] == ["1850", "Little mill words."]
    assert (child / "era_1850.png").read_bytes() == child_era.read_bytes()
    assert (adult / "era_1850.png").read_bytes() == adult_era.read_bytes()
    assert (child / "film.html").exists()


def game_for():
    return {"year": 1850, "era": "era_1850.png", "photo": "today.jpg",
            "differences": [
                {"text": "The sails are gone.", "change": "x"},
                {"text": "The base is brick.", "change": "y"},
                {"text": "New sails again.", "change": "z"}]}


def test_write_film_adds_the_spot_game_to_the_child_film(tmp_path):
    from PIL import Image

    era = tmp_path / "1850.png"
    Image.new("RGB", (16, 24), "blue").save(era)
    scenes = [child_scene(1850, "Little mill words.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                               photo="today.jpg", photo_credit="me",
                               era_files={"1850": str(era)},
                               folder="film/child", audience="child",
                               sibling="../film.json", spot=game_for())
    film = json.loads((out / "film.json").read_text())
    assert film["spot"] == "spot.html"
    assert (out / "spot.json").exists()
    page = (out / "spot.html").read_text()
    assert "The sails are gone." in page
    assert "era_1850.png" in page
    assert "film.html" in page


def test_write_film_marks_a_film_without_a_game(tmp_path):
    scenes = [child_scene(1850, "Little mill words.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert film["spot"] is None
    assert not (out / "spot.html").exists()


def test_caption_without_sentence_is_empty():
    stamp, sentence = builder.caption_for(scene(1779))
    assert (stamp, sentence) == ("1779", "")
    assert builder.filmable(scene(1779), []) is False
    assert builder.filmable(scene(1779, sentence="I opened."), []) is False


def kept_claim(year=1779, url="https://a.example/x",
               quote="The mill opened in 1779 after years of work."):
    return {"year": year, "url": url, "verdict": "supported",
            "claim": f"something happened in {year}", "quote": quote}


def test_filmable_needs_an_evidence_reference():
    made = scene(1779, sentence="I opened.")
    del made["caption_sentence"]["evidence"]
    assert builder.filmable(made, [kept_claim()]) is False


def test_filmable_accepts_a_matching_supported_claim():
    made = scene(1779, sentence="I opened.")
    made["caption_sentence"]["evidence"] = {
        "claim": "something happened in 1779",
        "url": "https://a.example/x",
        "quote": "The mill opened in 1779 after years of work."}
    assert builder.filmable(made, [kept_claim()]) is True


def test_filmable_refuses_a_refused_claim():
    made = scene(1779, sentence="I opened.")
    made["caption_sentence"]["evidence"] = {
        "claim": "something happened in 1779",
        "url": "https://a.example/x",
        "quote": "The mill opened in 1779 after years of work."}
    war = kept_claim()
    war["war_politics_only"] = True
    assert builder.filmable(made, [war]) is False
    hateful = kept_claim()
    hateful["refused_content"] = True
    assert builder.filmable(made, [hateful]) is False


def test_filmable_refuses_a_changed_claim():
    made = scene(1779, sentence="I opened.")
    made["caption_sentence"]["evidence"] = {
        "claim": "something happened in 1779",
        "url": "https://a.example/x",
        "quote": "The mill opened in 1779 after years of work."}
    changed = kept_claim()
    changed["claim"] = "renamed afterwards"
    assert builder.filmable(made, [changed]) is False
    dropped = kept_claim()
    dropped["verdict"] = "unsupported"
    assert builder.filmable(made, [dropped]) is False


def test_source_site_names_domain():
    assert builder.source_site("https://nl.wikipedia.org/wiki/X") == "Wikipedia"
    assert builder.source_site("https://www.kaagenbraassempromotie.nl/x") == "kaagenbraassempromotie.nl"


class DictCache:
    def __init__(self, texts):
        self.texts = texts

    def get(self, key):
        return self.texts.get(key)


LONG_QUOTE = "The old mill burnt down completely on the evening in question."


def cited_scene(year, url):
    made = scene(year, sentence=f"Words for {year}.", claim_url=url)
    made["caption_sentence"]["evidence"]["sentence_url"] = url
    return made


def test_end_sources_list_only_filmed_scenes():
    scenes = [cited_scene(1900, "https://a.example/1"),
              cited_scene(1900, "https://a.example/1")]
    claims = claims_for(scenes)
    claims.append({"year": 1930, "url": "https://b.example/2",
                   "verdict": "supported", "claim": "trimmed era",
                   "quote": LONG_QUOTE})
    cache = DictCache({"https://a.example/1": f"Intro. {LONG_QUOTE} Outro.",
                       "https://b.example/2": f"Intro. {LONG_QUOTE} Outro."})
    assert [entry["url"] for entry in builder.end_sources(scenes, claims, cache)] == [
        "https://a.example/1"]


def test_end_sources_carry_site_and_title():
    url = "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"
    scenes = [cited_scene(1900, url)]
    cache = DictCache({url: f"Intro. {LONG_QUOTE} Outro."})
    (entry,) = builder.end_sources(scenes, claims_for(scenes), cache)
    assert entry["site"] == "Wikipedia"
    assert entry["title"] == "De Adriaan, Haarlem"


def test_end_sources_prefers_the_pages_real_title():
    url = "https://example.com/tours-services/"
    scenes = [cited_scene(1900, url)]
    cache = DictCache({url: f"Intro. {LONG_QUOTE} Outro.",
                       url + "#title": "Tours & Services | Mill"})
    (entry,) = builder.end_sources(scenes, claims_for(scenes), cache)
    assert entry["title"] == "Tours & Services | Mill"


def test_end_sources_keeps_wikipedia_titles_from_the_url():
    url = "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"
    scenes = [cited_scene(1900, url)]
    cache = DictCache({url: f"Intro. {LONG_QUOTE} Outro.",
                       url + "#title": "De Adriaan, Haarlem - Wikipedia"})
    (entry,) = builder.end_sources(scenes, claims_for(scenes), cache)
    assert entry["title"] == "De Adriaan, Haarlem"


def test_end_sources_comes_from_the_stored_bundle():
    kept = cited_scene(1900, "https://a.example/1")
    refused = cited_scene(1900, "https://b.example/2")
    refused["caption_sentence"]["evidence"]["claim"] = "war thing"
    scenes = [kept, refused]
    claims = claims_for([kept])
    claims.append({"year": 1900, "url": "https://b.example/2",
                   "verdict": "supported", "claim": "war thing",
                   "quote": LONG_QUOTE, "war_politics_only": True})
    entries = builder.end_sources(scenes, claims, None)
    assert [entry["url"] for entry in entries] == ["https://a.example/1"]
    assert entries[0]["site"] == "a.example"
    assert entries[0]["title"] == "1"


def test_source_title_names_the_page():
    assert builder.source_title(
        "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem") == "De Adriaan, Haarlem"
    assert builder.source_title(
        "https://nl.wikipedia.org/w/index.php?title=De_Adriaan_(Haarlem)&oldid=1"
    ) == "De Adriaan (Haarlem)"
    assert builder.source_title(
        "https://www.molenadriaan.nl/en/tours-services/") == "tours services"
    assert builder.source_title("https://example.com/") == "example.com"


def test_film_json_carries_attribution(tmp_path):
    scenes = [scene(1779, "standing", "opened in 1779",
                    sentence="I opened my doors to the town.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [],
        "timings": {"identify_steps": {"overpass_s": 5}},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg",
                             photo_credit="A. Uthor, CC BY 4.0")
    film = json.loads((out / "film.json").read_text())
    assert "ready_at" not in film["scenes"][0]
    assert any("OpenStreetMap" in a for a in film["attribution"])
    assert film["photo_credit"] == "A. Uthor, CC BY 4.0"
    assert (out / "film.html").exists()


def test_film_carries_verified_kind_never_typed_place(tmp_path):
    scenes = [scene(1779, sentence="I opened my doors to the town.")]
    research = {
        "object": {"name": "Mill", "kind": "stellingmolen", "qid": "Q1",
                  "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert "place" not in film
    assert film["kind"] == "stellingmolen"
    import inspect
    assert "place" not in inspect.signature(builder.write_film).parameters


def test_film_scenes_carry_no_readiness(tmp_path):
    scenes = [scene(1779, sentence="I opened my doors to the town.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert "ready_at" not in film["scenes"][0]


def test_frame_count_covers_duration():
    from witness.render import record

    assert record.frame_times(10.0, fps=30)[-1] < 10.0
    assert len(record.frame_times(10.0, fps=30)) == 300
    assert record.frame_times(10.0, fps=30)[0] == 0.0


def test_record_loads_a_fixed_frame(tmp_path):
    from witness.render import record

    html = tmp_path / "film.html"
    html.write_text("<html></html>")
    url = record.page_url(html)
    assert url.endswith("film.html?t=0")


def test_frame_edges_detect_black_bars(tmp_path):
    from PIL import Image
    from witness.render import record

    barred = Image.new("RGB", (1080, 1920), "black")
    lit = Image.new("RGB", (1080, 1920), (90, 100, 110))
    assert record.edges_lit(barred) is False
    assert record.edges_lit(lit) is True


class _FakePage:
    def __init__(self):
        self.calls = []

    def goto(self, url):
        self.calls.append(("goto", url))

    def wait_for_function(self, js):
        self.calls.append(("wait", js))

    def evaluate(self, js):
        self.calls.append(("eval", js))

    def screenshot(self):
        return b"png"


class _FakePlaywright:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def chromium(self):
        return self

    def launch(self, **kwargs):
        return self

    def new_page(self, **kwargs):
        return self.page

    def close(self):
        pass


class _FakeProc:
    def __init__(self, code=0):
        self.frames = []
        self.closed = False
        self.code = code
        self.stdin = self
        self.target = None
        self.returncode = code

    def write(self, data):
        self.frames.append(data)

    def close(self):
        self.closed = True

    def communicate(self):
        self.close()
        if self.target is not None:
            Path(self.target).write_bytes(b"fake-mp4")
        return None, b""

    def wait(self, timeout=None):
        if self.target is not None:
            Path(self.target).write_bytes(b"fake-mp4")
        return self.code

    def terminate(self):
        pass

    def kill(self):
        pass

    def poll(self):
        return self.code


def _stub_recording(monkeypatch, page, proc):
    import playwright.sync_api
    from witness.render import record

    def popen(cmd, **kwargs):
        proc.target = cmd[-1]
        return proc

    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        lambda: _FakePlaywright(page))
    monkeypatch.setattr(record.subprocess, "Popen", popen)


def test_record_waits_for_ready_and_decoded_frames(tmp_path, monkeypatch):
    from witness.render import record

    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.1}]}))
    page, proc = _FakePage(), _FakeProc()
    _stub_recording(monkeypatch, page, proc)
    out = record.record(tmp_path / "film.html", tmp_path / "film.mp4")
    assert out == tmp_path / "film.mp4"
    waits = [js for kind, js in page.calls if kind == "wait"]
    assert waits[0] == record.READY_JS
    assert waits[1:] == [record.FRAME_JS] * 3  # one decoded frame each
    assert len(proc.frames) == 3
    assert proc.closed is True


class _PngPage(_FakePage):
    def __init__(self, shot):
        super().__init__()
        self.shot = shot

    def screenshot(self):
        return self.shot


def test_record_exports_a_real_mp4_through_ffmpeg(tmp_path, monkeypatch):
    """Complete synthetic export: real ffmpeg picks the mp4 muxer for
    the partial file, and a valid MP4 is published."""
    import io
    import shutil

    import pytest
    from PIL import Image

    import playwright.sync_api
    from witness.render import record

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(buf, format="PNG")
    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.1}]}))
    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        lambda: _FakePlaywright(_PngPage(buf.getvalue())))
    out = record.record(tmp_path / "film.html", tmp_path / "film.mp4")
    data = Path(out).read_bytes()
    assert data[4:8] == b"ftyp"
    assert list(tmp_path.glob("*.mp4.partial")) == []


def test_record_failure_keeps_bounded_ffmpeg_diagnostics(tmp_path, monkeypatch):
    """A failed encode reports ffmpeg's own error, capped in size."""
    import shutil
    import subprocess

    import pytest
    import playwright.sync_api
    from witness.render import record

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.03}]}))
    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        lambda: _FakePlaywright(_PngPage(b"not a picture")))
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        record.record(tmp_path / "film.html", tmp_path / "film.mp4")
    assert excinfo.value.stderr
    assert len(excinfo.value.stderr) <= 4096
    assert not (tmp_path / "film.mp4").exists()
    assert list(tmp_path.glob("*.mp4.partial")) == []


def test_record_raises_when_ffmpeg_fails(tmp_path, monkeypatch):
    import subprocess

    import pytest

    from witness.render import record

    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.03}]}))
    _stub_recording(monkeypatch, _FakePage(), _FakeProc(code=1))
    with pytest.raises(subprocess.CalledProcessError):
        record.record(tmp_path / "film.html", tmp_path / "film.mp4")


def test_rerender_leaves_no_stale_cutout(tmp_path):
    from PIL import Image

    cutout = tmp_path / "synthetic.png"
    Image.new("RGBA", (8, 8)).save(cutout)
    scenes = [scene(1779, sentence="I stood.")]
    research = {"object": {"name": "Tower"}, "claims": claims_for(scenes),
                "scenes": scenes}
    builder.write_film(tmp_path / "job", research, {"1779": "e/1779.png"},
                       "today.jpg", "", {}, cutout_file=cutout)
    film = builder.write_film(tmp_path / "job", research, {"1779": "e/1779.png"},
                              "today.jpg", "", {}, cutout_file=None)
    assert json.loads((film / "film.json").read_text())["cutout"] is None
    assert not (film / "cutout.png").exists()
    assert list((tmp_path / "job").glob("film.staging-*")) == []


def test_record_publishes_mp4_only_on_success(tmp_path, monkeypatch):
    from witness.render import record

    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.03}]}))
    proc = _FakeProc()
    _stub_recording(monkeypatch, _FakePage(), proc)
    out = record.record(tmp_path / "film.html", tmp_path / "film.mp4")
    assert proc.target != str(tmp_path / "film.mp4")
    assert proc.target.endswith(".mp4.partial")
    assert Path(out).read_bytes() == b"fake-mp4"
    assert list(tmp_path.glob("*.mp4.partial")) == []


def test_record_failure_leaves_no_mp4_and_kills_everything(
        tmp_path, monkeypatch):
    import subprocess

    import pytest

    from witness.render import record

    (tmp_path / "film.html").write_text("<html></html>")
    (tmp_path / "film.json").write_text(json.dumps(
        {"segments": [{"kind": "end", "start": 0, "end": 0.1}]}))

    class DyingPage(_FakePage):
        def evaluate(self, js):
            raise RuntimeError("synthetic browser death")

    class KillingProc(_FakeProc):
        def __init__(self):
            super().__init__(0)
            self.killed = []

        def terminate(self):
            self.killed.append("terminate")

        def kill(self):
            self.killed.append("kill")

        def poll(self):
            return None if "kill" not in self.killed else 0

    closed = []
    proc = KillingProc()

    class ClosingPlaywright(_FakePlaywright):
        def close(self):
            closed.append(True)

    import playwright.sync_api

    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        lambda: ClosingPlaywright(DyingPage()))
    monkeypatch.setattr(record.subprocess, "Popen", lambda *a, **k: proc)
    with pytest.raises(RuntimeError):
        record.record(tmp_path / "film.html", tmp_path / "film.mp4")
    assert not (tmp_path / "film.mp4").exists()
    assert list(tmp_path.glob("*.mp4.partial")) == []
    assert closed == [True]
    assert proc.killed[0] == "terminate"


def test_scene_site_uses_the_captions_own_evidence_url():
    made = scene(1865, sentence="I stood.")
    made["caption_sentence"]["evidence"]["sentence_url"] = \
        "https://nl.wikipedia.org/wiki/Y"
    assert builder.scene_site(made, [{"year": 1865,
                                      "url": "https://x.example/",
                                      "verdict": "supported"}]) == "Wikipedia"
    assert builder.scene_site(scene(1865), []) == ""


def test_caption_never_cuts_a_sentence():
    long = "I ground corn for the whole town and the villages round about."
    _, line2 = builder.caption_for(
        scene(1865, "standing", "word " * 30, sentence=long))
    assert line2 == long
    assert "…" not in line2


def test_film_captions_cite_own_year_claims(tmp_path):
    scenes = [scene(1779, "standing", "opened",
                    sentence="I opened my doors to the town."),
              scene(1865, "standing", "millstones",
                    sentence="My new millstones ground day and night.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research,
                             {"1779": "e/1779.png", "1865": "e/1865.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    lines = [entry["caption"][1] for entry in film["scenes"]]
    assert all("…" not in line for line in lines)
    assert len(set(lines)) == len(lines)
    for entry in film["scenes"]:
        assert entry["caption_claim"]["year"] == entry["year"]


def test_today_card_shows_photo_date_or_your_photo():
    last = scene(2002, "rebuilt", "whole again", sentence="I was rebuilt.")
    assert builder.today_card(2006, False, last, []) == (
        "Photographed in 2006.", "")
    assert builder.today_card(2012, False, last, []) == (
        "Photographed in 2012.", "")
    assert builder.today_card(2006, True, last, []) == (
        "Photographed in 2006.", "")
    assert builder.today_card(None, False, last, []) == ("Your photo.", "")
    gone = scene(1990, "demolished", "torn down",
                 sentence="I was torn down.")
    assert builder.today_card(None, False, gone, []) == ("Your photo.", "")
    assert builder.today_card(2006, False, gone, []) == (
        "Photographed in 2006.", "")


def test_film_drops_scenes_without_written_sentences(tmp_path):
    scenes = [scene(1779, "standing", "opened",
                    sentence="I opened my doors to the town."),
              scene(1865, "standing", "millstones")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research,
                             {"1779": "e/1779.png", "1865": "e/1865.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert [entry["year"] for entry in film["scenes"]] == [1779]
    eras = [seg for seg in film["segments"] if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1779]


def test_film_drops_sentences_without_a_claim(tmp_path):
    made = scene(1970, "standing", "scaffolding")
    made["caption_sentence"] = {
        "text": "Here I stood in 1970, much as always.",
        "claim_year": None, "claim_url": None}
    research = {
        "object": {"name": "Oak", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [made], "timeline": [], "timings": {},
    }
    import pytest

    with pytest.raises(ValueError, match="no filmable eras"):
        builder.write_film(tmp_path, research, {"1970": "e/1970.png"},
                           photo="today.jpg", photo_credit="me")


def test_film_html_plays_without_fetch(tmp_path):
    """film.json fetch is blocked on file:// pages, so the data is
    embedded in film.html and the page prefers it over fetch."""
    scenes = [scene(1779, "standing", "opened in 1779",
                    sentence="I opened.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me")
    html = (out / "film.html").read_text()
    assert '<script id="film-data" type="application/json">' in html
    blob = html.split('<script id="film-data" type="application/json">')[1]
    blob = blob.split("</script>")[0]
    assert json.loads(blob)["object"] == "Mill"
    # The unbuilt-template guard in the player script must survive injection.
    assert html.count("__FILM_JSON__") == 1


def test_write_film_serves_eras_byte_identical(tmp_path):
    from PIL import Image

    era = tmp_path / "1850.png"
    Image.new("RGB", (16, 24), "red").save(era)
    scenes = [scene(1850, "standing", "opened in 1779",
                    sentence="I opened my doors.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                             photo="today.jpg", photo_credit="me",
                             era_files={"1850": str(era)})
    assert (out / "era_1850.png").read_bytes() == era.read_bytes()
    assert not (out / "era_1850.jpg").exists()
    film = json.loads((out / "film.json").read_text())
    assert film["scenes"][0]["image"] == "era_1850.png"


def test_served_era_name_follows_the_bytes_not_the_filename(tmp_path):
    webp = tmp_path / "1850.png"
    webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8Xrest")
    assert builder.served_era_name("1850", str(webp)) == "era_1850.webp"
    png = tmp_path / "1865.webp"
    png.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    assert builder.served_era_name("1865", str(png)) == "era_1865.png"
    jpg = tmp_path / "1900.png"
    jpg.write_bytes(b"\xff\xd8\xff\xe0rest")
    assert builder.served_era_name("1900", str(jpg)) == "era_1900.jpg"
    with pytest.raises(ValueError):
        builder.served_era_name("1920", str(tmp_path / "missing.png"))


def test_film_scenes_carry_no_layers(tmp_path):
    scenes = [scene(1850, "standing", "opened in 1779",
                    sentence="I opened my doors.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert "layers" not in film["scenes"][0]
    assert not list(out.glob("layers_*"))





def _sourced_research():
    scenes = [scene(1779, "standing", "opened in 1779",
                    sentence="I opened my doors to the town.")]
    return {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [],
        "timings": {},
    }


def test_film_carries_photo_source_links(tmp_path):
    source = {"author": "A. Uthor", "licence": "CC BY 4.0",
              "licence_url": "https://creativecommons.org/licenses/by/4.0/",
              "file_url": "https://commons.wikimedia.org/wiki/File:X.JPG"}
    out = builder.write_film(tmp_path, _sourced_research(),
                             {"1779": "e/1779.png"}, photo="today.jpg",
                             photo_credit="Today photo: A. Uthor, CC BY 4.0",
                             photo_source=source)
    film = json.loads((out / "film.json").read_text())
    assert film["photo_source"] == source
    assert film["photo_credit"] == "Today photo: A. Uthor, CC BY 4.0"


def test_end_card_links_photo_source():
    template = (Path(builder.__file__).parent / "film.html").read_text()
    assert "photo_source" in template
    assert "licence_url" in template
    assert "file_url" in template


def test_end_card_links_are_large_on_phones():
    import re

    template = (Path(builder.__file__).parent / "film.html").read_text()
    sources = re.search(r"#sources \{([^}]*)\}", template).group(1)
    size = int(re.search(r"font-size: (\d+)px", sources).group(1))
    assert size >= 40, "source links must read at 390 px stage scale"
    item = re.search(r"#sources li \{([^}]*)\}", template).group(1)
    assert "padding:" in item, "source rows need a tappable height"


def extra_claim(year, claim, url="https://b.example/2", date_text=None,
                quote=None, **flags):
    made = {"year": year, "url": url, "verdict": "supported",
            "claim": claim, "date_text": date_text or str(year),
            "quote": quote if quote is not None else f"It was so in {year}."}
    made.update(flags)
    return made


def test_more_facts_lists_checked_facts_the_film_does_not_show():
    scenes = [scene(1850, sentence="I stood.")]
    claims = claims_for(scenes) + [
        extra_claim(1880, "extended (1880-1): Baptistery added at west end",
                    date_text="1880-1",
                    quote="The Baptistery was added in 1880-1."),
        extra_claim(1700, "In 1700 the roof was mended.",
                    url="https://c.example/3")]
    more = builder.more_facts(scenes, claims, {"1850": "e/1850.png"})
    assert more == [
        {"stamp": "1700", "text": "In 1700 the roof was mended.",
         "site": "c.example", "url": "https://c.example/3"},
        {"stamp": "1880", "text": "Baptistery added at west end",
         "site": "b.example", "url": "https://b.example/2"}]


def test_more_facts_never_lists_doubted_or_refused_claims():
    scenes = [scene(1850, sentence="I stood.")]
    claims = claims_for(scenes) + [
        dict(extra_claim(1900, "Half true."), verdict="partly"),
        dict(extra_claim(1901, "Not found."), verdict="unsupported"),
        dict(extra_claim(1902, "Never checked."), verdict="unverified"),
        extra_claim(1914, "A bomb went off.", war_politics_only=True),
        extra_claim(1915, "Hateful words.", refused_content=True),
        dict(extra_claim(1916, "No page."), url=""),
        dict(extra_claim(1917, "No year."), year=None)]
    assert builder.more_facts(scenes, claims, {"1850": "e/1850.png"}) == []


def test_more_facts_keeps_a_fact_whose_painting_was_dropped():
    scenes = [scene(1850, sentence="I stood."),
              scene(1900, sentence="I burnt.")]
    claims = claims_for(scenes)
    more = builder.more_facts(scenes, claims, {"1850": "e/1850.png"})
    assert [(m["stamp"], m["text"]) for m in more] == [
        ("1900", "Something happened in 1900")]
    # Before painting every caption-checked scene counts as shown.
    assert builder.more_facts(scenes, claims) == []


def test_more_facts_lists_a_repeated_fact_once():
    scenes = [scene(1850, sentence="I stood.")]
    claims = claims_for(scenes) + [
        extra_claim(1880, "The bell was hung."),
        extra_claim(1880, "The bell was hung.", url="https://c.example/3")]
    more = builder.more_facts(scenes, claims, {"1850": "e/1850.png"})
    assert [m["url"] for m in more] == ["https://b.example/2"]


def test_more_facts_stamp_follows_the_film_rule():
    scenes = [scene(1850, sentence="I stood.")]
    claims = claims_for(scenes) + [
        extra_claim(1914, "damaged (11 July 1914): The roof fell.",
                    date_text="11 July 1914",
                    quote="On 11 July 1914 the roof fell."),
        extra_claim(2011, "restored (July 2011): The organ was restored.",
                    date_text="July 2011",
                    quote="The organ was restored in July 2011.")]
    more = builder.more_facts(scenes, claims, {"1850": "e/1850.png"})
    assert [m["stamp"] for m in more] == ["11 July 1914", "2011"]
    assert [m["text"] for m in more] == ["The roof fell.",
                                         "The organ was restored."]


def test_more_facts_caps_the_list_and_skips_the_childrens_film():
    scenes = [scene(1850, sentence="I stood.")]
    claims = claims_for(scenes) + [
        extra_claim(1860 + i, f"Fact {i}.", url=f"https://b.example/{i}")
        for i in range(9)]
    more = builder.more_facts(scenes, claims, {"1850": "e/1850.png"})
    assert builder.MORE_MAX == 6
    assert [m["stamp"] for m in more] == [str(1860 + i) for i in range(6)]
    assert builder.more_facts(scenes, claims, {"1850": "e/1850.png"},
                              audience="child") == []


def test_end_sources_add_the_more_facts_pages_after_the_scenes():
    scenes = [cited_scene(1900, "https://a.example/1")]
    more = [{"stamp": "1880", "text": "x", "site": "b.example",
             "url": "https://b.example/2"},
            {"stamp": "1890", "text": "y", "site": "a.example",
             "url": "https://a.example/1"}]
    entries = builder.end_sources(scenes, claims_for(scenes), None, more=more)
    assert [entry["url"] for entry in entries] == [
        "https://a.example/1", "https://b.example/2"]


def test_write_film_lists_more_checked_facts_after_the_film(tmp_path):
    kept = scene(1850, sentence="I stood.")
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "short_film"},
        "claims": claims_for([kept]) + [
            extra_claim(1880, "extended (1880): A wing was added.")],
        "scenes": [kept], "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1850": "era_1850.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert film["more_facts"] == [
        {"stamp": "1880", "text": "A wing was added.", "site": "b.example",
         "url": "https://b.example/2"}]
    assert [s["url"] for s in film["sources"]] == [
        "https://a.example/x", "https://b.example/2"]
    assert [seg["kind"] for seg in film["segments"]] == [
        "title", "anchor", "era", "today", "end"]
