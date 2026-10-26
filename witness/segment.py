"""Step 1: cut the object out of today's photo (SAM 3.1), for the closing shot.

Text prompt first; when it yields no usable mask, a box prompt built with
meta_sam_parser. Box coordinates always come back in the sent image size
and are scaled back to the original here.
"""

import io
import re
from dataclasses import dataclass

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


class NoMaskError(Exception):
    """SAM returned no usable mask (caller may ask the user for a box)."""


@dataclass
class Cutout:
    box: tuple  # left, top, right, bottom in original pixels
    coverage: float  # fraction of original pixels masked
    mask: object  # PIL Image L, original size
    image: object  # PIL Image RGBA, original size


def segment(call_sam, photo, subject, box=None, max_dim=1600):
    """Cut out `subject`. `box` is (l, t, r, b) in original pixels, optional.

    `call_sam(input_text, jpeg_bytes)` sends one SAM request and returns the
    output text; production wires the Meta client, tests use fixtures.
    """
    original = Image.open(photo).convert("RGB")
    sent = original.copy()
    sent.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    sent.save(buf, format="JPEG", quality=88)

    raw = call_sam(subject, buf.getvalue())
    pair = largest(parse_output(raw))
    if pair == (None, None) and box is not None:
        prompt = build_object_prompt(
            size=sent.size,
            objects=[
                PromptObject(
                    id=0,
                    prompts=[FramePrompt(frame=0, box=_scaled_box(box, original.size, sent.size))],
                )
            ],
        )
        raw = call_sam(prompt, buf.getvalue())
        pair = largest(parse_output(raw))
    found_box, mask = pair
    if found_box is None:
        raise NoMaskError(f"no mask for {subject!r}")
    space = space_size(raw, *sent.size)
    mask_full, rgba = cutout(
        original,
        box=(found_box.left, found_box.top, found_box.right, found_box.bottom),
        raster=decode(mask),
        mask_size=(mask.width, mask.height),
        space=space,
    )
    on = sum(mask_full.histogram()[128:])
    sx, sy = original.width / space[0], original.height / space[1]
    return Cutout(
        box=(
            round(found_box.left * sx),
            round(found_box.top * sy),
            round(found_box.right * sx),
            round(found_box.bottom * sy),
        ),
        coverage=on / (original.width * original.height),
        mask=mask_full,
        image=rgba,
    )


def parse_output(text):
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    return parser.finish(CompletedOutcome()).result


def decode(mask):
    return decode_mask_to_raster(mask)


def largest(result):
    boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
    masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
    if not boxes or not masks:
        return (None, None)
    by_id = {b.object_id: b for b in boxes}
    best = max(masks, key=lambda r: _area(by_id[r.object_id]))
    return (by_id[best.object_id], best.mask)


def space_size(raw, sent_w, sent_h):
    """Coordinate space of the box tokens, from their w,h fields."""
    match = re.search(r"x1=\d+;y1=\d+;x2=\d+;y2=\d+;w=(\d+);h=(\d+)", raw)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (sent_w, sent_h)


def cutout(original, box, raster, mask_size, space):
    """Paste the decoded mask raster into a full-size mask; apply to pixels."""
    small = Image.frombytes("L", mask_size, bytes(v * 255 for v in raster))
    sx, sy = original.width / space[0], original.height / space[1]
    left, top = round(box[0] * sx), round(box[1] * sy)
    right, bottom = round(box[2] * sx), round(box[3] * sy)
    piece = small.resize((max(right - left, 1), max(bottom - top, 1)), Image.NEAREST)
    mask_full = Image.new("L", original.size, 0)
    mask_full.paste(piece, (left, top))
    rgba = original.copy()
    rgba.putalpha(mask_full)
    return (mask_full, rgba)


def _scaled_box(box, original_size, sent_size):
    sx = sent_size[0] / original_size[0]
    sy = sent_size[1] / original_size[1]
    left, top = int(box[0] * sx), int(box[1] * sy)
    right, bottom = int(box[2] * sx), int(box[3] * sy)
    return PromptBox(left=left, top=top, right=max(right, left + 1), bottom=max(bottom, top + 1))


def _area(box) -> float:
    return max(box.right - box.left, 0) * max(box.bottom - box.top, 0)
