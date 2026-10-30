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


def test_timeline_never_films_an_age_range():
    scenes = [age_scene(), scene(1790, sentence="I was renamed.")]
    plan = builder.build_timeline(
        scenes, {"1026": "e/1026.png", "1790": "e/1790.png"},
        claims_for(scenes))
    eras = [seg for seg in plan if seg["kind"] == "era"]
    assert [seg["year"] for seg in eras] == [1790]


def test_anchor_card_for_age_range_and_for_year():
    assert builder.anchor_card(age_scene()) == {
        "line": "I have stood here for",
        "label": "about 800 to 1,200 years"}
    assert builder.anchor_card(scene(1899)) == {
        "line": "I have stood here since", "label": "1899"}


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
    assert film["anchor"] == {"line": "I have stood here for",
                             "label": "about 800 to 1,200 years"}


def test_caption_is_a_date_stamp_and_one_sentence():
    stamp, sentence = builder.caption_for(
        scene(1779, "standing", "opened in 1779",
              sentence="I opened my doors to the town."))
    assert stamp == "1779"
    assert sentence == "I opened my doors to the town."
    stamped = scene(1932)
    stamped["date_label"] = "23 April 1932"
    stamp, _ = builder.caption_for(stamped)
    assert stamp == "23 April 1932"


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
    changed = kept_claim(quote="The mill opened in 1780 after years of work.")
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


def test_end_sources_dedupe_urls():
    claims = [
        {"url": "https://a.example/1", "quote": LONG_QUOTE, "verdict": "supported"},
        {"url": "https://a.example/1", "quote": LONG_QUOTE, "verdict": "supported"},
        {"url": "https://b.example/2", "quote": LONG_QUOTE, "verdict": "partly"},
        {"url": "https://c.example/3", "quote": LONG_QUOTE, "verdict": "unsupported"},
    ]
    cache = DictCache({"https://a.example/1": f"Intro. {LONG_QUOTE} Outro.",
                       "https://b.example/2": f"Intro. {LONG_QUOTE} Outro."})
    assert [entry["url"] for entry in builder.end_sources(claims, cache)] == [
        "https://a.example/1"]


def test_end_sources_carry_site_and_title():
    claims = [
        {"url": "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem",
         "quote": LONG_QUOTE, "verdict": "supported"},
    ]
    cache = DictCache({"https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem":
                       f"Intro. {LONG_QUOTE} Outro."})
    (entry,) = builder.end_sources(claims, cache)
    assert entry["site"] == "Wikipedia"
    assert entry["title"] == "De Adriaan, Haarlem"


def test_end_sources_prefers_the_pages_real_title():
    url = "https://example.com/tours-services/"
    claims = [{"url": url, "quote": LONG_QUOTE, "verdict": "supported"}]
    cache = DictCache({url: f"Intro. {LONG_QUOTE} Outro.",
                       url + "#title": "Tours & Services | Mill"})
    (entry,) = builder.end_sources(claims, cache)
    assert entry["title"] == "Tours & Services | Mill"


def test_end_sources_keeps_wikipedia_titles_from_the_url():
    url = "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"
    claims = [{"url": url, "quote": LONG_QUOTE, "verdict": "supported"}]
    cache = DictCache({url: f"Intro. {LONG_QUOTE} Outro.",
                       url + "#title": "De Adriaan, Haarlem - Wikipedia"})
    (entry,) = builder.end_sources(claims, cache)
    assert entry["title"] == "De Adriaan, Haarlem"


def test_end_sources_comes_from_the_stored_bundle():
    claims = [
        {"url": "https://a.example/1", "quote": LONG_QUOTE, "verdict": "supported"},
        {"url": "https://b.example/2", "quote": LONG_QUOTE, "verdict": "supported",
         "war_politics_only": True},
        {"url": "https://c.example/3", "quote": "", "verdict": "supported"},
        {"url": "https://d.example/4", "quote": LONG_QUOTE, "verdict": "unsupported"},
    ]
    entries = builder.end_sources(claims, None)
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


def test_film_json_carries_readiness_and_attribution(tmp_path):
    scenes = [scene(1779, "standing", "opened in 1779",
                    sentence="I opened my doors to the town.")]
    research = {
        "object": {"name": "Mill", "qid": "Q1", "lang": "en"},
        "outcome": {"outcome": "full_film"},
        "claims": claims_for(scenes),
        "scenes": scenes,
        "timeline": [],
        "timings": {"identify_steps": {"overpass_s": 5}},
        "stream": [{"event": "scene_painted", "year": 1779, "t": 54.4,
                    "verdict": "matches"}],
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg",
                             photo_credit="A. Uthor, CC BY 4.0")
    film = json.loads((out / "film.json").read_text())
    assert film["scenes"][0]["ready_at"] == 54.4
    assert any("OpenStreetMap" in a for a in film["attribution"])
    assert film["photo_credit"] == "A. Uthor, CC BY 4.0"
    assert (out / "film.html").exists()


def test_film_carries_verified_kind_never_typed_place(tmp_path):
    research = {
        "object": {"name": "Mill", "kind": "stellingmolen", "qid": "Q1",
                  "lang": "en"},
        "outcome": {"outcome": "full_film"}, "claims": [],
        "scenes": [scene(1779, sentence="I opened my doors to the town.")],
        "timeline": [], "timings": {},
    }
    out = builder.write_film(tmp_path, research, {"1779": "e/1779.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert "place" not in film
    assert film["kind"] == "stellingmolen"
    import inspect
    assert "place" not in inspect.signature(builder.write_film).parameters


def test_film_without_stream_events_is_ready_at_once(tmp_path):
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
    assert film["scenes"][0]["ready_at"] == 0


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

    def write(self, data):
        self.frames.append(data)

    def close(self):
        self.closed = True

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
    research = {"object": {"name": "Tower"}, "scenes": []}
    builder.write_film(tmp_path / "job", research, {}, "today.jpg", "", {},
                       cutout_file=cutout)
    film = builder.write_film(tmp_path / "job", research, {}, "today.jpg",
                              "", {}, cutout_file=None)
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


def test_scene_site_falls_back_to_year_claims():
    assert builder.scene_site(
        scene(1865), [{"year": 1865, "url": "https://nl.wikipedia.org/wiki/Y",
                       "verdict": "supported"}]) == "Wikipedia"
    assert builder.scene_site(scene(1865), [{"year": 1900, "url": "https://x.example/",
                                             "verdict": "supported"}]) == ""


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


def test_today_card_names_a_stale_photo_year():
    last = scene(2026, "standing", "canopy leafless",
                 sentence="I stand leafless.")
    line, sub = builder.today_card(2006, False, last, [])
    assert line == "And here I stand today."
    assert sub == "Photographed in 2006."


def test_today_card_silent_for_fresh_or_own_photos():
    last = scene(2002, "rebuilt", "whole again", sentence="I was rebuilt.")
    assert builder.today_card(2012, False, last, []) == (
        "And here I stand today.", "")
    assert builder.today_card(2006, True, last, []) == (
        "And here I stand today.", "")
    assert builder.today_card(None, False, last, []) == (
        "And here I stand today.", "")


def test_today_card_never_repeats_the_last_line():
    died = scene(2026, "standing", "canopy leafless",
                 sentence="The RSPB announced I died.")
    claims = [{"year": 2026, "url": "https://a.example/x", "event": "died",
               "verdict": "supported"}]
    assert builder.today_card(2006, False, died, claims) == (
        "", "Photographed in 2006.")
    gone = scene(1990, "demolished", "torn down",
                 sentence="I was torn down.")
    assert builder.today_card(None, False, gone, []) == (
        "And here I stood.", "")


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
    out = builder.write_film(tmp_path, research, {"1970": "e/1970.png"},
                             photo="today.jpg", photo_credit="me")
    film = json.loads((out / "film.json").read_text())
    assert film["scenes"] == []


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



