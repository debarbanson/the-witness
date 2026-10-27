"""Step 6: people as layers. SAM finds the period figures in each
painted era; every figure becomes its own RGBA layer so the renderer
can move them at a different speed from the background (parallax).
"""

import io

from meta_sam_parser import SegmentationBoxRecord, SegmentationMaskRecord
from PIL import Image

from witness import segment

MAX_FIGURES = 16


def figures(call_sam, image_path, subject="person", max_figures=MAX_FIGURES,
            max_dim=1600):
    """Figure layers largest first. `call_sam` matches segment.segment."""
    original = Image.open(image_path).convert("RGB")
    sent = original.copy()
    sent.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    sent.save(buf, format="JPEG", quality=88)
    raw = call_sam(subject, buf.getvalue())
    result = segment.parse_output(raw)
    boxes = {r.object_id: r for r in result.records
             if isinstance(r, SegmentationBoxRecord)}
    pairs = [(boxes[m.object_id], m.mask) for m in result.records
             if isinstance(m, SegmentationMaskRecord) and m.object_id in boxes]
    pairs.sort(key=lambda pair: _area(pair[0]), reverse=True)
    space = segment.space_size(raw, *sent.size)
    sx, sy = original.width / space[0], original.height / space[1]
    out = []
    for box, mask in pairs[:max(max_figures, 0)]:
        _, rgba = segment.cutout(
            original,
            box=(box.left, box.top, box.right, box.bottom),
            raster=segment.decode(mask),
            mask_size=(mask.width, mask.height),
            space=space,
        )
        out.append({"box": (round(box.left * sx), round(box.top * sy),
                            round(box.right * sx), round(box.bottom * sy)),
                    "image": rgba})
    return out


def _area(box) -> float:
    return (box.right - box.left) * (box.bottom - box.top)
