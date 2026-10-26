"""Probe 1: cut "windmill" out of the CC0 De Adriaan photo with sam-3.1.

Saves source.json (photo URL, page, licence), sam_response.json,
sam_raw.txt, sam_result.json, mask.png and object.png to out/probes/.
"""

import json
import re
from pathlib import Path

from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
)
from PIL import Image

from probes.common import OUT, client, data_uri, response_json, save_json, save_text

SOURCE_PAGE = (
    "https://commons.wikimedia.org/wiki/"
    "File:De_Adriaan,_Windmill,_Haarlem,_The_Netherlands.jpg"
)
SOURCE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/5/5c/"
    "De_Adriaan%2C_Windmill%2C_Haarlem%2C_The_Netherlands.jpg"
)
LICENCE = "CC0 (Creative Commons Zero, Public Domain Dedication)"

SUBJECT = "windmill"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(
        "source.json",
        {
            "page": SOURCE_PAGE,
            "url": SOURCE_URL,
            "licence": LICENCE,
            "subject": SUBJECT,
        },
    )

    src_path = OUT / "source.jpg"
    original = Image.open(src_path).convert("RGB")
    orig_w, orig_h = original.size

    uri, (sent_w, sent_h) = data_uri(src_path)
    resp = client().responses.create(
        model="sam-3.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SUBJECT},
                    {"type": "input_image", "image_url": uri},
                ],
            }
        ],
    )
    save_json("sam_response.json", response_json(resp))

    raw = ""
    for item in resp.output or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", None) == "output_text":
                raw += block.text
    if not raw:
        raise SystemExit("sam-3.1 returned no output_text; see sam_response.json")
    save_text("sam_raw.txt", raw)

    parser = image_segmentation_format().create_parser()
    parser.push(raw)
    finish = parser.finish(CompletedOutcome())
    result = finish.result

    boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
    masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
    save_json(
        "sam_result.json",
        {
            "sent_size": [sent_w, sent_h],
            "original_size": [orig_w, orig_h],
            "outcome": {"status": result.outcome.status},
            "diagnostics": [
                {"severity": d.severity, "code": d.code, "message": d.message}
                for d in result.diagnostics
            ],
            "boxes": [
                {
                    "object_id": b.object_id,
                    "left": b.left,
                    "top": b.top,
                    "right": b.right,
                    "bottom": b.bottom,
                    "confidence": b.confidence,
                }
                for b in boxes
            ],
            "masks": [
                {
                    "object_id": m.object_id,
                    "raster": [m.mask.width, m.mask.height],
                    "encoding": m.mask.encoding,
                    "bounds": [
                        m.bounds.left,
                        m.bounds.top,
                        m.bounds.right,
                        m.bounds.bottom,
                    ],
                    "confidence": m.confidence,
                }
                for m in masks
            ],
        },
    )
    print(f"boxes={len(boxes)} masks={len(masks)}")
    if not masks or not boxes:
        raise SystemExit("no usable mask records; see sam_result.json")

    # Coordinate space of the box tokens: w,h fields of the raw record.
    m = re.search(r"x1=\d+;y1=\d+;x2=\d+;y2=\d+;w=(\d+);h=(\d+)", raw)
    if m:
        space_w, space_h = int(m.group(1)), int(m.group(2))
    else:
        space_w, space_h = sent_w, sent_h
    print(f"coord space={space_w}x{space_h} sent={sent_w}x{sent_h} orig={orig_w}x{orig_h}")

    # Keep the largest instance by box area.
    by_id = {b.object_id: b for b in boxes}
    best = max(masks, key=lambda r: _area(by_id[r.object_id]))
    box = by_id[best.object_id]
    print(f"largest: id={best.object_id} box=({box.left},{box.top},{box.right},{box.bottom})")

    # Decode the mask raster (bytes of 0/1) and place it on the full image.
    raster = decode_mask_to_raster(best.mask)
    assert len(raster) == best.mask.width * best.mask.height
    small = Image.frombytes("L", (best.mask.width, best.mask.height), bytes(v * 255 for v in raster))

    sx, sy = orig_w / space_w, orig_h / space_h
    left = round(box.left * sx)
    top = round(box.top * sy)
    right = round(box.right * sx)
    bottom = round(box.bottom * sy)
    piece = small.resize((max(right - left, 1), max(bottom - top, 1)), Image.NEAREST)

    mask = Image.new("L", (orig_w, orig_h), 0)
    mask.paste(piece, (left, top))
    mask.save(OUT / "mask.png")

    cutout = original.copy()
    cutout.putalpha(mask)
    cutout.save(OUT / "object.png")
    print(f"saved object.png and mask.png ({orig_w}x{orig_h})")


def _area(box: SegmentationBoxRecord) -> float:
    return max(box.right - box.left, 0) * max(box.bottom - box.top, 0)


if __name__ == "__main__":
    main()
