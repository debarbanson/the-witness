"""Probe 6: retry the SAM cut-out with a fuller prompt, else a box prompt.

First tries "windmill with its brick base" as input_text. If the mask still
misses the base (checked by eye), run again with --box to send a box prompt
built by meta_sam_parser instead. Saves sam_retry_*.json/png.
"""

import re
import sys

from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptBox,
    PromptObject,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    build_object_prompt,
    decode_mask_to_raster,
    image_segmentation_format,
)
from PIL import Image

from probes.common import OUT, client, data_uri, response_json, save_json, save_text

PROMPT = "windmill with its brick base"
# Hand box around the whole mill, in the 1600x1200 sent image: generous.
BOX = (500, 80, 1300, 1130)


def main() -> None:
    use_box = "--box" in sys.argv
    stem = "sam_retry_box" if use_box else "sam_retry"

    original = Image.open(OUT / "source.jpg").convert("RGB")
    orig_w, orig_h = original.size
    uri, (sent_w, sent_h) = data_uri(OUT / "source.jpg")

    if use_box:
        text = build_object_prompt(
            size=(sent_w, sent_h),
            objects=[
                PromptObject(
                    id=0,
                    prompts=[
                        FramePrompt(
                            frame=0,
                            box=PromptBox(
                                left=BOX[0], top=BOX[1], right=BOX[2], bottom=BOX[3]
                            ),
                        )
                    ],
                )
            ],
        )
        print(f"box prompt text: {text[:120]}")
    else:
        text = PROMPT

    resp = client().responses.create(
        model="sam-3.1",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": uri},
                ],
            }
        ],
    )
    save_json(f"{stem}_response.json", response_json(resp))

    raw = ""
    for item in resp.output or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", None) == "output_text":
                raw += block.text
    if not raw:
        raise SystemExit("no output_text; see response json")
    save_text(f"{stem}_raw.txt", raw)

    parser = image_segmentation_format().create_parser()
    parser.push(raw)
    result = parser.finish(CompletedOutcome()).result
    boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
    masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
    print(f"boxes={len(boxes)} masks={len(masks)}")
    if not masks or not boxes:
        raise SystemExit("no usable records")

    m = re.search(r"x1=\d+;y1=\d+;x2=\d+;y2=\d+;w=(\d+);h=(\d+)", raw)
    space_w, space_h = (int(m.group(1)), int(m.group(2))) if m else (sent_w, sent_h)

    by_id = {b.object_id: b for b in boxes}
    best = max(masks, key=lambda r: _area(by_id[r.object_id]))
    box = by_id[best.object_id]
    print(f"largest: id={best.object_id} box=({box.left},{box.top},{box.right},{box.bottom})")

    raster = decode_mask_to_raster(best.mask)
    small = Image.frombytes(
        "L", (best.mask.width, best.mask.height), bytes(v * 255 for v in raster)
    )
    sx, sy = orig_w / space_w, orig_h / space_h
    left, top = round(box.left * sx), round(box.top * sy)
    right, bottom = round(box.right * sx), round(box.bottom * sy)
    piece = small.resize((max(right - left, 1), max(bottom - top, 1)), Image.NEAREST)
    mask = Image.new("L", (orig_w, orig_h), 0)
    mask.paste(piece, (left, top))
    mask.save(OUT / f"{stem}_mask.png")
    cutout = original.copy()
    cutout.putalpha(mask)
    cutout.save(OUT / f"{stem}_object.png")
    on = sum(mask.histogram()[128:])
    print(f"on-fraction={on / (orig_w * orig_h):.4f}")


def _area(box: SegmentationBoxRecord) -> float:
    return max(box.right - box.left, 0) * max(box.bottom - box.top, 0)


if __name__ == "__main__":
    main()
