"""Step 7: the renderer builds a live film page. No live calls."""

import json

from witness.render import builder


def scene(year, condition="standing", description="", lines=()):
    return {"from_year": year, "date_label": str(year),
            "state": {"condition": condition, "degree": "total",
                      "scope": "whole", "description": description},
            "caption_lines": [{"year": year, "line": line,
                               "url": "https://nl.wikipedia.org/wiki/X"}
                              for line in lines]}


def test_timeline_gives_every_part_its_seconds():
    plan = builder.build_timeline(
        [scene(1779), scene(1865)], {"1779": "e/1779.png", "1865": "e/1865.png"})
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
    plan = builder.build_timeline([scene(1779), scene(1865)], {"1865": "e/1865.png"})
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1865]


def test_caption_is_first_person_in_two_lines():
    line1, line2 = builder.caption_for(
        scene(1779, "standing", "opened in 1779"))
    assert line1 == "I stood here in 1779."
    assert line2 == "opened in 1779"


def test_caption_templates_per_condition():
    assert builder.caption_for(scene(1932, "burnt", "base left"))[0] == "I burned in 1932."
    assert builder.caption_for(scene(1999, "under_construction", "scaffolded"))[0].startswith(
        "I was being rebuilt")
    assert builder.caption_for(scene(2019, "moved", "70 m inland"))[0] == "I moved in 2019."
    assert builder.caption_for(scene(2002, "rebuilt", "whole again"))[0] == "I was rebuilt in 2002."


def test_caption_second_line_falls_back_to_caption_line():
    long = "x" * 200
    _, line2 = builder.caption_for(scene(1779, "standing", long, ["barges on the quay"]))
    assert line2 == "barges on the quay"


def test_source_site_names_domain():
    assert builder.source_site("https://nl.wikipedia.org/wiki/X") == "Wikipedia"
    assert builder.source_site("https://www.kaagenbraassempromotie.nl/x") == "kaagenbraassempromotie.nl"


def test_end_sources_dedupe_urls():
    claims = [
        {"url": "https://a.example/1", "quote": "q", "verdict": "supported"},
        {"url": "https://a.example/1", "quote": "q", "verdict": "supported"},
        {"url": "https://b.example/2", "quote": "q", "verdict": "partly"},
        {"url": "https://c.example/3", "quote": "q", "verdict": "unsupported"},
    ]
    assert builder.end_sources(claims) == ["https://a.example/1", "https://b.example/2"]


def test_film_json_carries_readiness_and_attribution(tmp_path):
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": [{"url": "https://a.example/1", "quote": "q",
                    "verdict": "supported"}],
        "scenes": [scene(1779, "standing", "opened in 1779")],
        "timeline": [],
        "timings": {"identify_steps": {"overpass_s": 5}},
        "stream": [{"event": "scene_painted", "year": 1779, "t": 54.4,
                    "verdict": "matches"}],
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg",
                             photo_credit="A. Uthor, CC BY 4.0",
                             layers={})
    film = json.loads((out / "film.json").read_text())
    assert film["scenes"][0]["ready_at"] == 54.4
    assert any("OpenStreetMap" in a for a in film["attribution"])
    assert film["photo_credit"] == "A. Uthor, CC BY 4.0"
    assert (out / "film.html").exists()


def test_film_without_stream_events_is_ready_at_once(tmp_path):
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [scene(1779)], "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me", layers={})
    film = json.loads((out / "film.json").read_text())
    assert film["scenes"][0]["ready_at"] == 0


def test_frame_count_covers_duration():
    from witness.render import record

    assert record.frame_times(10.0, fps=30)[-1] < 10.0
    assert len(record.frame_times(10.0, fps=30)) == 300
    assert record.frame_times(10.0, fps=30)[0] == 0.0


def test_scene_site_falls_back_to_year_claims():
    assert builder.scene_site(
        scene(1865), [{"year": 1865, "url": "https://nl.wikipedia.org/wiki/Y",
                       "verdict": "supported"}]) == "Wikipedia"
    assert builder.scene_site(scene(1865), [{"year": 1900, "url": "https://x.example/",
                                             "verdict": "supported"}]) == ""


def test_caption_trims_long_description_without_caption_lines():
    _, line2 = builder.caption_for(scene(1865, "standing", "word " * 30))
    assert len(line2) <= 57
    assert line2.endswith("…")


def test_film_html_plays_without_fetch(tmp_path):
    """film.json fetch is blocked on file:// pages, so the data is
    embedded in film.html and the page prefers it over fetch."""
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [scene(1779, "standing", "opened in 1779")],
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me", layers={})
    html = (out / "film.html").read_text()
    assert '<script id="film-data" type="application/json">' in html
    blob = html.split('<script id="film-data" type="application/json">')[1]
    blob = blob.split("</script>")[0]
    assert json.loads(blob)["object"] == "Mill"
    # The unbuilt-template guard in the player script must survive injection.
    assert html.count("__FILM_JSON__") == 1
