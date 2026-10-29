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
