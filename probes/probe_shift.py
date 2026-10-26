"""Probe 4b (TEST): how far does the windmill move between chained turns?

Segments "windmill" with sam-3.1 in anchor.png, era_1850.png and
era_1950.png and compares the largest box per image. Saves
image_shift.json to out/probes/.
"""

from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    image_segmentation_format,
)

from probes.common import OUT, client, data_uri, save_json

IMAGES = ["anchor", "era_1850", "era_1950"]


def main() -> None:
    boxes = {}
    for name in IMAGES:
        uri, (w, h) = data_uri(OUT / f"{name}.png", max_dim=1600)
        resp = client().responses.create(
            model="sam-3.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "windmill"},
                        {"type": "input_image", "image_url": uri},
                    ],
                }
            ],
        )
        raw = ""
        for item in resp.output or []:
            for block in getattr(item, "content", None) or []:
                if getattr(block, "type", None) == "output_text":
                    raw += block.text
        parser = image_segmentation_format().create_parser()
        parser.push(raw)
        result = parser.finish(CompletedOutcome()).result
        found = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
        best = max(found, key=lambda b: (b.right - b.left) * (b.bottom - b.top))
        boxes[name] = {
            "size": [w, h],
            "box": [best.left, best.top, best.right, best.bottom],
            "cx": (best.left + best.right) / 2 / w,
            "cy": (best.top + best.bottom) / 2 / h,
            "bw": (best.right - best.left) / w,
            "bh": (best.bottom - best.top) / h,
        }
        print(name, boxes[name])

    base = boxes["anchor"]
    shifts = {}
    for name in ["era_1850", "era_1950"]:
        b = boxes[name]
        shifts[name] = {
            "dx_fraction_of_width": round(b["cx"] - base["cx"], 4),
            "dy_fraction_of_height": round(b["cy"] - base["cy"], 4),
            "width_ratio": round(b["bw"] / base["bw"], 3),
            "height_ratio": round(b["bh"] / base["bh"], 3),
        }
    save_json("image_shift.json", {"boxes": boxes, "shifts_vs_anchor": shifts})
    print(shifts)


if __name__ == "__main__":
    main()
