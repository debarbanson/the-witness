"""Probe 4: anchored era painting with muse-image-1.0.

Anchor turn: the CC0 De Adriaan photo as input_image, establishing framing
and style. Era turns: chained with previous_response_id, painting the same
view in 1850 and in 1950 at 1024x1536 (1080x1920 is rejected by the
API) with enable_image_search false.

Saves image_anchor.json, image_1850.json, image_1950.json (full responses)
and whatever images come back (anchor.png, era_1850.png, era_1950.png).
"""

import base64
import json
from pathlib import Path

from probes.common import OUT, client, data_uri, response_json, save_json

STYLE = (
    "Painterly historical illustration, soft daylight, muted period colours. "
    "Keep the windmill's position, scale and perspective exactly as in the input photo."
)
# Day-1 finding: the API rejects size 1080x1920 (unknown value). 1024x1536 is
# the closest portrait size it accepts; the renderer crops to 1080x1920 later.
SIZE = "1024x1536"


def _tools():
    return [
        {
            "type": "image_generation",
            "size": SIZE,
            "enable_image_search": False,
        }
    ]

ERAS = {
    "era_1850": (
        "Repaint this exact view around the year 1850: the Spaarne river with "
        "wooden barges, cobbled banks, townspeople in mid-19th century dress, "
        "horse carts, no cars, no modern signs. " + STYLE
    ),
    "era_1950": (
        "Repaint this exact view around the year 1950: the Spaarne river with "
        "early motorboats and bicycles along the quay, people in 1950s dress, "
        "a few vintage cars, no modern signs. " + STYLE
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    api = client()
    uri, sent_size = data_uri(OUT / "source.jpg", max_dim=1024)
    print(f"anchor input size={sent_size}")

    anchor = api.responses.create(
        model="muse-image-1.0",
        tools=_tools(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "This photo is the anchor for a series of historical "
                            "illustrations of the same place. Describe the framing "
                            "and establish the style for the series: " + STYLE
                        ),
                    },
                    {"type": "input_image", "image_url": uri},
                ],
            }
        ],
    )
    save_json("image_anchor.json", response_json(anchor))
    print(f"anchor id={anchor.id}")
    _save_images("image_anchor.json", "anchor")

    prev = anchor.id
    for name, prompt in ERAS.items():
        resp = api.responses.create(
            model="muse-image-1.0",
            tools=_tools(),
            previous_response_id=prev,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        )
        save_json(f"image_{name.split('_')[1]}.json", response_json(resp))
        print(f"{name} id={resp.id}")
        _save_images(f"image_{name.split('_')[1]}.json", name)
        prev = resp.id


def _save_images(json_name: str, stem: str) -> None:
    """Find image payloads in a saved response and write them to disk."""
    data = json.loads((OUT / json_name).read_text())
    found = 0
    for b64 in _walk_b64(data):
        raw = base64.b64decode(b64)
        path = OUT / f"{stem}.png"
        path.write_bytes(raw)
        print(f"saved {path} ({len(raw)} bytes)")
        found += 1
    if not found:
        print(f"WARNING: no image payload found in {json_name}; inspect it by hand")


def _walk_b64(node):
    """Yield base64 image strings from likely response shapes."""
    if isinstance(node, dict):
        if node.get("type") == "image_generation_call" and node.get("result"):
            yield node["result"]
            return
        for key in ("b64_json", "image_base64", "base64"):
            if isinstance(node.get(key), str) and len(node[key]) > 1000:
                yield node[key]
        for value in node.values():
            yield from _walk_b64(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_b64(value)


if __name__ == "__main__":
    main()
