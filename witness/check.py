"""Step 5: check each painting against the object's verified state.

The painting goes to Muse Spark as input_image with the state text and
one question. The model call is injected, so tests run without live
calls.
"""

import base64
import io


def check_prompt(object_name, state_text) -> str:
    """Matches or differs, verdict first, then what the model sees."""
    return (
        f"Verified state of {object_name} in this painting: {state_text} "
        f"Look at the painting. Does it show {object_name} in that state? "
        f"Answer with the single word MATCHES or DIFFERS first, then one "
        f"sentence saying what you see."
    )


def check_painting(check_call, image_bytes, object_name, state_text) -> dict:
    """One vision check. Anything but MATCHES first counts as differs:
    nothing reaches the film unverified."""
    answer = (check_call(image_bytes, check_prompt(object_name, state_text))
              or "").strip()
    first, _, rest = answer.partition(" ")
    if first.strip(" :.,").upper() == "MATCHES":
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
