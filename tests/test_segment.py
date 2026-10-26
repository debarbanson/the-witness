"""Step 1: SAM cut-out with box fallback. No live calls."""

from pathlib import Path

import pytest
from PIL import Image

from witness import segment

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_text_prompt_records():
    result = segment.parse_output((FIXTURES / "sam_windmill.txt").read_text())
    box, mask = segment.largest(result)
    assert box.object_id == "1"
    assert (box.right - box.left) > 500


def test_parse_box_prompt_records():
    result = segment.parse_output((FIXTURES / "sam_box.txt").read_text())
    box, mask = segment.largest(result)
    assert box.object_id == "0"
    assert len(segment.decode(mask)) == mask.width * mask.height


def test_largest_with_no_records_is_none():
    result = segment.parse_output("no objects here\n")
    assert segment.largest(result) == (None, None)


def test_space_size_reads_box_tokens():
    raw = (FIXTURES / "sam_windmill.txt").read_text()
    assert segment.space_size(raw, 1600, 1200) == (1600, 1200)
    assert segment.space_size("nothing", 800, 600) == (800, 600)


def test_cutout_scales_box_back_to_original():
    original = Image.new("RGB", (100, 80), (10, 20, 30))
    mask_full, rgba = segment.cutout(
        original,
        box=(10, 8, 30, 24),  # in a 50x40 space
        raster=bytes([1] * 100),
        mask_size=(10, 10),
        space=(50, 40),
    )
    assert mask_full.size == (100, 80)
    assert rgba.size == (100, 80) and rgba.mode == "RGBA"
    # Box (10,8,30,24) in 50x40 space maps to (20,16,60,48) in 100x80.
    assert mask_full.getpixel((0, 0)) == 0
    assert mask_full.getpixel((40, 32)) == 255
    assert mask_full.getpixel((70, 60)) == 0
    assert rgba.getpixel((40, 32)) == (10, 20, 30, 255)


def fake_photo(path, size=(200, 160)):
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def test_segment_text_prompt(tmp_path):
    photo = fake_photo(tmp_path / "p.jpg")
    calls = []

    def call_sam(input_text, jpeg_bytes):
        calls.append(input_text)
        assert jpeg_bytes[:2] == b"\xff\xd8"
        return (FIXTURES / "sam_windmill.txt").read_text()

    cut = segment.segment(call_sam, photo, "windmill")
    assert calls == ["windmill"]
    assert cut.coverage > 0.01
    assert cut.image.size == (200, 160)


def test_segment_falls_back_to_box(tmp_path):
    photo = fake_photo(tmp_path / "p.jpg")
    calls = []

    def call_sam(input_text, jpeg_bytes):
        calls.append(input_text)
        if input_text.startswith("<"):
            return (FIXTURES / "sam_box.txt").read_text()
        return "no objects here\n"

    cut = segment.segment(call_sam, photo, "windmill", box=(20, 16, 180, 144))
    assert len(calls) == 2
    assert "<|box;" in calls[1] and "w=200;h=160" in calls[1]
    assert cut.coverage > 0.01


def test_segment_no_records_and_no_box_raises(tmp_path):
    photo = fake_photo(tmp_path / "p.jpg")
    with pytest.raises(segment.NoMaskError):
        segment.segment(lambda t, b: "no objects here\n", photo, "windmill")
