"""Parser checks against the recorded day-1 SAM response (no API calls)."""

from pathlib import Path

from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sam_windmill.txt"


def _parse():
    parser = image_segmentation_format().create_parser()
    parser.push(FIXTURE.read_text())
    return parser.finish(CompletedOutcome()).result


def test_recorded_response_parses_with_boxes_and_masks():
    result = _parse()
    boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
    masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
    assert len(boxes) == 2
    assert len(masks) == 2
    assert result.outcome.status == "completed"


def test_largest_box_is_the_windmill_upper_works():
    result = _parse()
    boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
    best = max(boxes, key=lambda b: (b.right - b.left) * (b.bottom - b.top))
    assert best.object_id == "1"
    assert (best.right - best.left) > 500
    assert (best.bottom - best.top) > 500


def test_largest_mask_decodes_to_its_raster_size():
    result = _parse()
    masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
    best = max(masks, key=lambda m: m.mask.width * m.mask.height)
    raster = decode_mask_to_raster(best.mask)
    assert len(raster) == best.mask.width * best.mask.height
    assert any(raster)
