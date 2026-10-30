"""Step 5: check each painting against the object's verified state.

The painting goes to Muse Spark as input_image with the state text and
one question. The model call is injected, so tests run without live
calls.
"""

import base64
import io
import re

# A MATCHES hedged by any of these is not a match: the painting
# check never passes a qualified verdict.
QUALIFIERS = frozenset({
    "mostly", "partly", "partially", "almost", "somewhat", "roughly",
    "largely", "generally", "more or less", "sort of", "kind of",
})


def check_prompt(object_name, state_text, year, caption="",
                   season=None) -> str:
    """The whole scene, one verdict: the object in its state, no
    lettering, nothing the year could not hold, nothing contradicting
    its own caption, every object detail from the verified state, and
    the expected season without snow. Winter expects nothing: snow
    may or may not lie."""
    base = (
        f"Verified state of {object_name} in this painting: {state_text} "
        f"The painting is dated {year}. Look at the whole painting. Answer "
        f"MATCHES only if all hold: (1) it shows {object_name} in "
        f"that state; (2) it holds no readable text, dates, signs, "
        f"captions or signatures; (3) nothing in it postdates {year}: no "
        f"aircraft, paragliders, cranes, cars, modern clothing, street "
        f"furniture or other anachronisms; (4) every visible detail of "
        f"the object itself comes from the verified state above: a "
        f"detail the sources never state DIFFERS")
    number = 5
    if caption:
        base += (f"; ({number}) the scene agrees with its caption: {caption}. "
                 f"A painting that contradicts its own caption DIFFERS")
        number += 1
    if season in ("spring", "summer", "autumn"):
        base += (f"; ({number}) the season is {season}: no snow or ice "
                 f"on the ground")
    return (base + ". Otherwise answer with the single word DIFFERS first, "
            "then one sentence saying what is wrong.")


def check_painting(check_call, image_bytes, object_name, state_text, year,
                   caption="", season=None) -> dict:
    """One vision check. Anything but MATCHES first counts as differs:
    nothing reaches the film unverified."""
    answer = (check_call(image_bytes, check_prompt(object_name, state_text, year, caption, season))
              or "").strip()
    first, _, rest = answer.partition(" ")
    if first.strip(" :.,").upper() == "MATCHES":
        lowered = f" {answer.lower()} "
        if any(re.search(rf"\b{re.escape(found)}\b", lowered) for found in QUALIFIERS):
            return {"verdict": "differs",
                    "note": f"qualified match ({answer.strip() or answer})"}
        return {"verdict": "matches", "note": rest.strip() or answer}
    return {"verdict": "differs", "note": rest.strip() or answer}


def data_uri(image_bytes, max_dim=1024):
    """Downscaled PNG as a data URI plus its pixel size."""
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    uri = ("data:image/png;base64,"
           + base64.b64encode(buf.getvalue()).decode("ascii"))
    return uri, image.size
