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
    assert "Every era it lived through, painted from your photo." in page
    assert '<h1 class="hero-title">' in page
    assert "every fact sourced" in page.lower()
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
    assert "sourced history" in page
    assert "Painted eras" in page
    assert "returns to your photo" in page
    for src in ("/assets/landing/step1.jpg", "/assets/landing/step3.webp"):
        assert src in page
        assert client.get(src).status_code == 200


def test_accuracy_promise_states_the_code(tmp_path):
    page = _page(tmp_path)
    assert "every fact shown links to the page it came from" in page.lower()
    assert "claims without a source are left out" in page.lower()
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
    assert "Family version" in page
    assert "/examples/de-adriaan/child/film.html" in page
    assert client.get("/examples/de-adriaan/era_1932.webp").status_code == 200


def test_gallery_without_a_child_hides_the_pill(tmp_path):
    import shutil

    deps = _deps(tmp_path)
    shutil.rmtree(tmp_path / "examples" / "de-adriaan" / "child")
    client = TestClient(create_app(deps), headers=dict(ORIGIN))
    page = client.get("/").text
    assert "Family version" not in page


def test_try_your_own_says_what_works_and_how_long(tmp_path):
    page = _page(tmp_path)
    assert "tower, windmill, lighthouse, old tree or bridge" in page
    assert "about 8 minutes" in page
    assert "facts instead of a film" in page
    assert "by design" in page
    assert 'id="upload"' in page
    assert 'id="geo"' in page
    assert 'href="/privacy"' in page


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


def test_try_your_own_privacy_is_three_bullets(tmp_path):
    import re as _re

    page = _page(tmp_path)
    notice = _re.search(r'<section id="notice">(.*?)</section>', page,
                        _re.S).group(1)
    assert notice.count("<li>") == 3
    assert "Full notice" in notice
    assert 'name="ack"' in page
    for name in ("Meta", "Baseten", "Modal", "Nominatim", "Overpass",
                 "Wikidata", "Wikipedia"):
        assert name in notice


def test_try_your_own_shows_tries_and_left(tmp_path):
    page = _page(tmp_path)
    assert "tries a day" in page
    assert "left today" in page
    assert "Resets tomorrow" in page


def test_try_your_own_progress_is_a_step_list(tmp_path):
    page = _page(tmp_path)
    for step in ("Identify", "Research", "Check", "Paint", "Film"):
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


def test_gallery_credits_today_photo_from_source(tmp_path):
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
    assert "Tomasz Sienicki" in cards
    assert "CC BY 4.0" in cards
    client = TestClient(create_app(_deps(tmp_path)),
                        headers=dict(ORIGIN))
    assert client.get("/").status_code == 200


def test_family_wording_replaces_children_version(tmp_path):
    page = _page(tmp_path)
    assert "Family version" in page
    assert "children's version" not in page.lower()
    assert "8+" not in page


def test_try_your_own_carries_the_18plus_line(tmp_path):
    page = _page(tmp_path)
    assert "For adults 18 and over" in page


def test_player_audience_button_says_family():
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "witness" / "render"
            / "film.html").read_text()
    assert '"Family"' in html
    assert '"Children"' not in html


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
    for name in ("README.md", "docs/08_children.md", "docs/04_demo.md"):
        text = (root / name).read_text()
        lowered = text.lower()
        assert "children's version" not in lowered, name
        assert "8+" not in text, name
        assert "children aged" not in lowered, name


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


def test_try_your_own_promises_no_second_version(tmp_path):
    from pathlib import Path

    page = _page(tmp_path)
    assert "Writing the family version" not in page
    assert "Making spot-the-difference" not in page
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "Uploads make the adult film only." in readme
