"""Step 5: the painting check. Model calls are injected; no live calls."""

import base64
import io

from witness import check


def test_check_prompt_quotes_state_and_demands_verdict_first():
    prompt = check.check_prompt("De Adriaan", "burnt, only the base left", 1932)
    assert "burnt, only the base left" in prompt
    assert "MATCHES" in prompt and "DIFFERS" in prompt


def test_check_painting_parses_matches():
    out = check.check_painting(lambda image, prompt: "MATCHES whole mill shown.",
                               b"img", "De Adriaan", "standing, whole", 1850)
    assert out == {"verdict": "matches", "note": "whole mill shown."}


def test_check_painting_parses_differs_case_insensitively():
    out = check.check_painting(lambda image, prompt: "differs: shows sails.",
                               b"img", "De Adriaan", "burnt, base left", 1932)
    assert out == {"verdict": "differs", "note": "shows sails."}


def test_check_painting_treats_unparseable_as_differs():
    out = check.check_painting(lambda image, prompt: "The painting is nice.",
                               b"img", "De Adriaan", "standing, whole", 1850)
    assert out["verdict"] == "differs"
    assert "nice" in out["note"]


def test_data_uri_resizes_and_labels_png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 200), "red").save(buf, "PNG")
    uri, size = check.data_uri(buf.getvalue(), max_dim=100)
    assert uri.startswith("data:image/png;base64,")
    assert size == (50, 100)
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert Image.open(io.BytesIO(raw)).size == (50, 100)


def test_check_prompt_asks_about_text_and_anachronisms():
    prompt = check.check_prompt("De Adriaan", "burnt, only the base left", 1932)
    assert "1932" in prompt
    assert "readable text" in prompt
    assert "paraglider" in prompt or "aircraft" in prompt
    assert "MATCHES only if" in prompt


def test_check_prompt_adds_caption_agreement():
    prompt = check.check_prompt("De Adriaan", "under construction", 1999,
                                caption="My first pile was put in the ground.")
    assert "My first pile was put in the ground." in prompt
    assert "contradicts" in prompt
    plain = check.check_prompt("De Adriaan", "under construction", 1999)
    assert "contradicts" not in plain


def test_check_prompt_adds_a_snow_free_season():
    prompt = check.check_prompt("Mill", "standing", 1932, season="spring")
    assert "spring" in prompt
    assert "no snow" in prompt
    assert "(4)" in prompt


def test_check_prompt_numbers_season_after_caption():
    prompt = check.check_prompt("Mill", "standing", 1932,
                                caption="I burnt down.", season="autumn")
    assert "(5)" in prompt
    assert "autumn" in prompt


def test_check_prompt_skips_season_for_winter_and_none():
    assert "no snow" not in check.check_prompt("Mill", "standing", 1932,
                                                season="winter")
    plain = check.check_prompt("Mill", "standing", 1932)
    assert "no snow" not in plain


def test_check_painting_passes_season_to_the_question():
    seen = []

    def ask(image, prompt):
        seen.append(prompt)
        return "MATCHES agree."

    check.check_painting(ask, b"img", "Mill", "standing", 1932,
                         season="summer")
    assert "summer" in seen[0]


def test_check_painting_passes_caption_to_the_question():
    seen = []

    def ask(image, prompt):
        seen.append(prompt)
        return "MATCHES agree."

    check.check_painting(ask, b"img", "De Adriaan", "under construction",
                         1999, caption="My first pile was put in the ground.")
    assert "My first pile was put in the ground." in seen[0]


def test_check_painting_rejects_qualified_matches():
    ask = lambda image, prompt: "MATCHES, mostly."
    assert check.check_painting(ask, b"img", "Mill", "standing", 1932)[
        "verdict"] == "differs"
    ask = lambda image, prompt: "MATCHES fine."
    assert check.check_painting(ask, b"img", "Mill", "standing", 1932)[
        "verdict"] == "matches"


def test_check_prompt_rejects_unsupported_painted_detail():
    prompt = check.check_prompt("Mill", "The mill stands whole.", 1932)
    assert "every visible detail of the object" in prompt
    assert "the sources never state" in prompt
