"""The landing page: a judge understands it in 10 seconds."""

import re

from fastapi.testclient import TestClient

from witness import webapp
from witness.webapp import MemoryStore, WebDeps, create_app

ORIGIN = {"Origin": "http://testserver"}
REFUSED = ("Not in the film: in July 2020 the tree was reported as "
           "vandalised, with a three-foot section of bark fallen off. "
           "No fetched source confirmed it.")


def _deps(tmp_path, **overrides):
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    examples_root = tmp_path / "examples"
    (examples_root / "de-adriaan").mkdir(parents=True, exist_ok=True)
    (examples_root / "de-adriaan" / "film.html").write_text(
        "<html><head></head><body>synthetic film</body></html>")
    (examples_root / "de-adriaan" / "film.json").write_text(
        '{"object": "De Adriaan", "segments": [{"year": null}, '
        '{"year": 1779}, {"year": 1932}, {"year": 2002}, '
        '{"year": null}]}')
    (examples_root / "de-adriaan" / "today.jpg").write_bytes(
        b"synthetic-today")
    (examples_root / "de-adriaan" / "era_1932.webp").write_bytes(
        b"synthetic-era")
    child = examples_root / "de-adriaan" / "child"
    child.mkdir(parents=True, exist_ok=True)
    (child / "film.html").write_text(
        "<html><head></head><body>synthetic child film</body></html>")
    args = dict(store=MemoryStore(), authority=None,
                runner=lambda ref: "test-receipt",
                jobs_root=jobs_root, examples_root=examples_root,
                examples=[{"slug": "de-adriaan",
                           "name": "De Adriaan, Haarlem"}],
                contact="owner@example.com", clock=lambda: 1000.0)
    args.update(overrides)
    return WebDeps(**args)


def _client(tmp_path, **overrides):
    return TestClient(create_app(_deps(tmp_path, **overrides)),
                      headers=dict(ORIGIN))


def _page(tmp_path, **overrides):
    out = _client(tmp_path, **overrides).get("/")
    assert out.status_code == 200
    return out.text


def test_hero_says_what_it_does_with_a_preview(tmp_path):
    page = _page(tmp_path)
    assert "One photo. The turning points it has witnessed, painted and sourced." in page
    assert '<h1 class="hero-title">' in page
    assert "checks every fact against a source" in page
    assert "The film ends on your own photo." in page
    assert "De Adriaan, Haarlem: opened 1779, burnt 1932, rebuilt 2002." in page
    assert re.search(r'<video[^>]*muted[^>]*loop[^>]*playsinline', page)
    assert "/assets/landing/hero.mp4" in page
    assert "/assets/landing/hero-poster.jpg" in page
    assert "prefers-reduced-motion" in page


def test_hero_preview_is_eight_to_twelve_seconds():
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("ffprobe") is None:
        import pytest

        pytest.skip("ffprobe not installed")
    hero = (Path(webapp.__file__).resolve().parent / "landing"
            / "hero.mp4")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(hero)],
        capture_output=True, text=True, check=True)
    assert 8 <= float(out.stdout.strip()) <= 12


def test_how_it_works_has_three_steps_with_real_frames(tmp_path):
    client = _client(tmp_path)
    page = client.get("/").text
    assert "Your photo" in page
    assert "Its history, with sources" in page
    assert "Painted through time" in page
    assert "The film ends on your photo." in page
    for src in ("/assets/landing/step1.jpg", "/assets/landing/step3.webp"):
        assert src in page
        assert client.get(src).status_code == 200


def test_accuracy_promise_states_the_code(tmp_path):
    page = _page(tmp_path)
    assert "every fact on screen links to the page it came from" in page.lower()
    assert "a claim without a confirming source is left out" in page.lower()
    assert "it doesn't guarantee historical truth" in page.lower()
    assert REFUSED in page
    assert "Major Oak" in page


def test_gallery_card_per_example_with_span_and_both_pictures(tmp_path):
    client = _client(tmp_path)
    page = client.get("/").text
    assert "De Adriaan, Haarlem" in page
    assert "1779" in page and "2002" in page
    assert "/examples/de-adriaan/" in page
    assert "/examples/de-adriaan/era_1932.webp" in page
    assert "/examples/de-adriaan/today.jpg" in page
    assert "Picture-book version" in page
    assert "/examples/de-adriaan/child/film.html" in page
    assert client.get("/examples/de-adriaan/era_1932.webp").status_code == 200


def test_gallery_without_a_child_hides_the_pill(tmp_path):
    import shutil

    deps = _deps(tmp_path)
    shutil.rmtree(tmp_path / "examples" / "de-adriaan" / "child")
    client = TestClient(create_app(deps), headers=dict(ORIGIN))
    page = client.get("/").text
    assert "Picture-book version" not in page


def test_try_your_own_says_what_works_and_how_long(tmp_path):
    page = _page(tmp_path)
    assert "windmill, tower, lighthouse, bridge or old tree" in page
    assert "about 7 minutes" in page
    assert "measured on two films" in page
    assert "The checked facts appear after about 4 minutes" in page
    assert "the painted film follows" in page
    assert "updated after the owner's phone films" not in page
    assert "checked facts instead" in page
    assert "by design" in page
    assert 'id="upload"' in page
    assert 'id="loc-auto"' in page
    assert 'id="geo"' not in page
    assert 'href="/privacy"' in page


def test_how_it_works_names_both_checking_models(tmp_path):
    page = _page(tmp_path)
    assert ("Muse Spark Open and Muse Spark check every claim against "
            "the page it came from. Anything that can't be checked is "
            "left out.") in page
    assert "state-setting follow-ups" not in page


def test_examples_intro_promises_no_game(tmp_path):
    page = _page(tmp_path)
    assert ("Three landmarks, researched and painted. Two also have a "
            "picture-book version.") in page
    assert "with a spot-the-difference game" not in page


def test_try_intro_warns_about_war_shaped_histories(tmp_path):
    page = _page(tmp_path)
    line = ("Castles and forts often have histories shaped by war, which "
            "The Witness leaves out, so they may not give a film.")
    assert line in page
    assert page.index("Works best with") < page.index(line)


def test_confirmed_name_reaches_text_only(tmp_path):
    import re

    page = _page(tmp_path)
    script = re.search(r'<script nonce="[^"]*">(.*?)</script>', page,
                       re.S).group(1)
    for name, args in (("showConfirm", "st"), ("decide", "confirm"),
                       ("renderSub", "st, now"), ("showResult", "box, st")):
        body = re.search(r"function " + name + r"\(" + args + r"\) \{.*?\n\}",
                         script, re.S)
        assert body, "no " + name
        assert "innerHTML" not in body.group(0), name


def test_free_credit_terms_in_notice_and_form(tmp_path):
    page = _page(tmp_path)
    privacy = _client(tmp_path).get("/privacy").text
    for text in (page, privacy):
        assert "free developer credits" in text
        assert "may use what we send it to improve its products" in text


def test_privacy_notice_explains_the_saved_job_id(tmp_path):
    privacy = " ".join(_client(tmp_path).get("/privacy").text.split())
    assert ("Your browser keeps the job id (localStorage) so you can come "
            "back to a running film; it is cleared when the film ends or "
            "is gone.") in privacy


def test_phone_hero_shows_the_film_first(tmp_path):
    page = _page(tmp_path)
    assert '<h1 class="hero-title">' in page
    assert 'class="hero-media"' in page
    assert 'class="lede"' in page
    assert ".hero-left{display:contents}" in page
    assert ".hero-title{" in page and "order:1" in page
    assert ".hero-media{" in page and "order:2" in page
    assert ".hero-body{" in page and "order:3" in page
    assert "max-width:240px" in page or "max-width:220px" in page


def test_top_nav_stays_on_one_line(tmp_path):
    page = _page(tmp_path)
    assert 'class="only-wide"' in page
    assert ".only-wide" in page
    assert "flex-wrap:nowrap" in page or "white-space:nowrap" in page
    assert page.count('href="/privacy"') >= 2


def test_desktop_hero_centres_and_follows_the_loop(tmp_path):
    page = _page(tmp_path)
    assert "align-items:center" in page
    assert ".hero-left{display:flex" in page
    assert "justify-content:center" in page
    assert ".years li.playing" in page
    assert "timeupdate" in page
    assert "hero-facts" in page
    assert "painted era" in page
    assert "every fact linked to its source" in page


def test_how_it_works_is_three_equal_panels(tmp_path):
    client = _client(tmp_path)
    page = client.get("/").text
    assert "repeat(3" in page
    assert "De Adriaan was officially opened on May 19, 1779." in page
    assert "1779" in page
    assert "en.wikipedia.org/wiki/De_Adriaan" in page
    assert "/assets/landing/step1.jpg" in page
    assert "/assets/landing/step3.webp" in page
    assert "/assets/landing/step2.jpg" not in page
    assert client.get("/assets/landing/step1.jpg").status_code == 200


def test_try_your_own_has_a_styled_picker_with_preview(tmp_path):
    page = _page(tmp_path)
    assert "Take or choose a photo" in page
    assert 'id="preview"' in page
    assert "createObjectURL" in page
    assert "#preview.hidden" in page
    csp = _client(tmp_path).get("/").headers["Content-Security-Policy"]
    assert "img-src 'self' blob:" in csp


def test_try_your_own_usage_is_one_compact_paragraph(tmp_path):
    page = _page(tmp_path)
    assert '<section id="notice">' not in page
    assert "Step 3: How your photo is used" in page
    assert "Your photo is sent to Meta and Baseten" in page
    assert "OpenStreetMap services, Wikidata and Wikipedia" in page
    assert "Full notice" in page
    assert 'name="ack"' in page
    assert "I understand how my photo is used." in page


def test_try_your_own_shows_films_left(tmp_path):
    page = _page(tmp_path)
    assert "Films left today in this browser:" in page
    assert "daily limit per network and overall" in page
    assert "Resets tomorrow" in page
    assert ("Every started film uses one of your tries, even when the "
            "landmark can't be recognised.") in page


def test_try_your_own_progress_is_a_step_list(tmp_path):
    page = _page(tmp_path)
    for step in ("Recognise", "Research", "Check", "Paint", "Film"):
        assert step in page
    assert 'data-step="identify"' in page
    assert ".done::before" in page or ".step-done" in page


def test_try_your_own_off_hides_the_form(tmp_path):
    page = _page(tmp_path, try_enabled=lambda: False)
    assert "Try your own is resting" in page
    assert "example films above still play" in page
    assert 'id="upload"' not in page


def test_footer_credits_only_live_path_models(tmp_path):
    page = _page(tmp_path)
    assert "Meta Global AI Developer Hackathon" in page
    assert "Muse Spark" in page
    assert "Muse Image" in page
    assert "Muse Spark Open (via Baseten)" in page
    assert "SAM 3.1" in page
    assert "cutout" in page.lower()
    assert "github.com/debarbanson/the-witness" in page
    assert "owner@example.com" in page


def test_landing_serves_its_font_and_keeps_the_licence(tmp_path):
    from pathlib import Path

    client = _client(tmp_path)
    out = client.get("/assets/fonts/fraunces-600.woff2")
    assert out.status_code == 200
    assert out.headers["content-type"] == "font/woff2"
    assert "@font-face" in client.get("/").text
    root = Path(webapp.__file__).resolve().parent / "landing" / "fonts"
    assert "SIL OPEN FONT LICENSE" in (root / "OFL.txt").read_text()


def test_landing_keeps_the_strict_csp(tmp_path):
    from witness.webapp import _style_hashes

    out = _client(tmp_path).get("/")
    assert out.text.count("<style>") == 1
    assert _style_hashes(out.text)
    assert "style=" not in out.text
    assert "<script" in out.text and out.text.count("<script") == 1
    assert 'nonce="' in out.text
    assert "__NONCE__" not in out.text
    cleaned = out.text.replace(
        "https://github.com/debarbanson/the-witness", "").replace(
        "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem", "")
    assert "https://" not in cleaned


def test_landing_is_shaped_for_phones_and_keyboards(tmp_path):
    page = _page(tmp_path)
    assert 'name="viewport"' in page
    assert "<html" in page and 'lang="en"' in page
    for tag in re.findall(r"<img[^>]*>", page):
        assert 'alt="' in tag and re.search(r'alt="[^"]', tag)
    assert ":focus-visible" in page
    assert not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", page)


def test_landing_names_no_tools(tmp_path):
    import re as _re

    page = _page(tmp_path).lower()
    text = _re.sub(r"<style>.*?</style>", "", page, flags=_re.S)
    for name in ("claude", "codex", "copilot", "chatgpt", "daypages"):
        assert name not in text


def test_landing_palette_meets_aa_contrast():
    import re as _re

    css = _re.search(r"<style>(.*?)</style>", webapp.INDEX_PAGE,
                     _re.S).group(1)
    tokens = dict(_re.findall(r"--(\w+):(#[0-9a-f]+)", css))

    def luminance(hexed):
        channels = [int(hexed[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        shaped = [v / 12.92 if v <= 0.03928
                  else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return 0.2126 * shaped[0] + 0.7152 * shaped[1] + 0.0722 * shaped[2]

    def ratio(first, second):
        light, dark = sorted((luminance(first), luminance(second)),
                             reverse=True)
        return (light + 0.05) / (dark + 0.05)

    paper, card = tokens["paper"], tokens["card"]
    for text in ("ink", "muted", "accent"):
        for base in (paper, card):
            assert ratio(tokens[text], base) >= 4.5, (text, base)
    assert ratio(paper, tokens["ink"]) >= 4.5


def test_archival_photo_labels_say_photo_not_today(tmp_path):
    page = _page(tmp_path)
    assert "<li>photo</li>" in page
    assert "<li>today</li>" not in page
    assert "Today photo:" not in page


def test_gallery_credits_photo_from_source(tmp_path):
    import json as _json

    from fastapi.testclient import TestClient

    from witness.webapp import _gallery_cards

    base = tmp_path / "examples" / "rubjerg-knude"
    base.mkdir(parents=True)
    (base / "film.json").write_text(_json.dumps(
        {"object": "Rubjerg Knude Fyr", "segments": [{"year": 1899}],
         "photo_credit": "",
         "photo_source": {"author": "Tomasz Sienicki",
                          "licence": "CC BY 4.0"}}))
    cards = _gallery_cards(tmp_path / "examples",
                           [{"slug": "rubjerg-knude",
                             "name": "Rubjerg Knude lighthouse, Denmark"}])
    assert "Photo: Tomasz Sienicki" in cards
    assert "CC BY 4.0" in cards
    assert "Today photo:" not in cards
    client = TestClient(create_app(_deps(tmp_path)),
                        headers=dict(ORIGIN))
    assert client.get("/").status_code == 200


def test_family_wording_replaces_children_version(tmp_path):
    page = _page(tmp_path)
    assert "Picture-book version" in page
    assert "children's version" not in page.lower()
    assert "8+" not in page


def test_no_adult_words_in_user_facing_text(tmp_path):
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    page = _page(tmp_path)
    privacy = _client(tmp_path).get("/privacy").text
    texts = {"landing": page, "privacy": privacy}
    for name in ("README.md", "docs/01_brief.md", "docs/02_pipeline.md",
                 "docs/04_demo.md", "docs/06_web.md", "docs/07_test_set.md",
                 "docs/08_picture_book.md", "witness/render/film.html",
                 "witness/render/spot.html"):
        texts[name] = (root / name).read_text()
    for where, text in texts.items():
        clean = re.sub(r"`[^`]*`", "", text).lower()
        assert "adult" not in clean, where


def test_no_age_line_on_landing_page(tmp_path):
    page = _page(tmp_path)
    assert "18 and over" not in page
    assert "18 or older" not in page


def test_privacy_notice_has_one_age_sentence(tmp_path):
    privacy = _client(tmp_path).get("/privacy").text
    assert privacy.count("You must be 18 or older to upload a photo.") == 1
    assert "For adults 18 and over" not in privacy


def test_recognising_phase_names_the_model(tmp_path):
    page = _page(tmp_path)
    assert 'recognising: "Recognising the landmark (Muse Spark)"' in page
    assert "recognising: 0" in page


def test_place_field_has_label_and_placeholder(tmp_path):
    import re

    page = _page(tmp_path)
    assert re.search(r"<label[^>]*>.*?<input[^>]*name=\"place\"",
                     page, re.S), "place field has no label"
    assert 'placeholder="De Adriaan, Haarlem"' in page


def test_player_audience_button_says_family():
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "witness" / "render"
            / "film.html").read_text()
    assert '"Picture-book"' in html
    assert '"Children"' not in html
    assert '"Family"' not in html


def test_playing_family_film_and_game_calls_no_api():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "witness" / "render"
    film = (root / "film.html").read_text()
    spot = (root / "spot.html").read_text()
    for text in (film, spot):
        assert "/api" not in text
        assert "http" not in text
        assert "XMLHttpRequest" not in text
    assert "fetch(" not in spot


def test_user_facing_docs_say_family_not_children():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ("README.md", "docs/08_picture_book.md", "docs/04_demo.md"):
        text = (root / name).read_text()
        lowered = text.lower()
        assert "children's version" not in lowered, name
        assert "8+" not in text, name
        assert "children aged" not in lowered, name


def test_no_audience_words_in_user_facing_text(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    page = _page(tmp_path)
    privacy = _client(tmp_path).get("/privacy").text
    texts = {"landing": page, "privacy": privacy}
    for name in ("README.md", "docs/01_brief.md", "docs/02_pipeline.md",
                 "docs/04_demo.md", "docs/06_web.md", "docs/07_test_set.md",
                 "docs/08_picture_book.md"):
        texts[name] = (root / name).read_text()
    for where, text in texts.items():
        lowered = text.lower().replace("font-family", "")
        assert "family" not in lowered, where
        assert "children" not in lowered, where
        assert "kids" not in lowered, where
        assert "younger" not in lowered, where


def test_step_list_labels_follow_the_event_model(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "steps_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:500]


def test_confirm_question_names_the_place(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "confirm_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:500]


def test_model_calls_toggle_lists_the_job_rows(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "calls_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:500]


def test_checked_facts_panel_lists_only_the_facts_after_the_film(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "facts_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_location_help_asks_only_when_needed(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "location_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_try_your_own_promises_no_second_version(tmp_path):
    from pathlib import Path

    page = _page(tmp_path)
    assert "Writing the family version" not in page
    assert "Making spot-the-difference" not in page
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "Uploads make the film only." in readme


def test_landing_states_photo_retention_plainly(tmp_path):
    page = _page(tmp_path)
    assert "within about a day" in page
    assert "26 hours" in page


def test_locked_phone_resume_keeps_the_film(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    for mode in ("resume", "misses", "gone", "cancel"):
        out = subprocess.run([node, str(check), str(target), mode],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, f"{mode}: {out.stderr[:500]}"


def test_one_tap_makes_one_film(tmp_path):
    """4 Nov: "Make my film" stayed silent during the upload, a second
    tap started a second film under a second visitor id, and two polling
    loops fought over the page. The first tap must show the upload at
    once and block every further tap until the film ends."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "submit_check.cjs"
    for mode in ("double", "fail", "refused", "resumed"):
        out = subprocess.run([node, str(check), str(target), mode],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, f"{mode}: {out.stderr[:500]}"


def test_clock_follows_server_elapsed_time(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    out = subprocess.run([node, str(check), str(target), "clock"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_painting_shows_checked_facts_then_the_film(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    out = subprocess.run([node, str(check), str(target), "facts"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_result_end_states_list_sources(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "result_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_too_little_end_state_skips_paint_and_film(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    for mode in ("toolittle", "failed", "notconfirmed", "notidentified"):
        out = subprocess.run([node, str(check), str(target), mode],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, f"{mode}: {out.stderr[:2000]}"


def test_sub_progress_lines_come_from_job_events(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "sub_check.cjs"
    out = subprocess.run([node, str(check), str(target)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_facts_only_end_keeps_the_check_count(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    out = subprocess.run([node, str(check), str(target), "subcheck"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]


def test_confirm_tap_hides_buttons_with_feedback(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node not installed")
    page = _page(tmp_path)
    target = tmp_path / "landing.html"
    target.write_text(page)
    check = Path(__file__).parent / "resume_check.cjs"
    for mode in ("decide", "decidefail", "decidefailhttp"):
        out = subprocess.run([node, str(check), str(target), mode],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, f"{mode}: {out.stderr[:2000]}"
