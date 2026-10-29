"""One clean copy of the upload: upright, stripped, always today.jpg."""

import io

from PIL import Image

from witness import photo


def _portrait_jpeg(path):
    """A portrait photo stored sideways (orientation 6) with GPS EXIF."""
    img = Image.new("RGB", (40, 80), (120, 60, 30))
    exif = Image.Exif()
    exif[274] = 6  # orientation: rotate to view upright
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N",
                   2: (52.0, 9.0, 36.0), 3: "E", 4: (4.0, 21.0, 0.0)}
    img.save(path, exif=exif)
    return path


def test_prepare_transposes_and_strips(tmp_path):
    src = _portrait_jpeg(tmp_path / "upload.jpg")
    assert Image.open(src).size == (40, 80)
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert dest.name == "today.jpg"
    clean = Image.open(dest)
    assert clean.size == (80, 40)
    assert dict(clean.getexif()) == {}
    assert clean.mode == "RGB"


def test_prepare_accepts_png(tmp_path):
    src = tmp_path / "upload.png"
    Image.new("RGB", (30, 20), (10, 200, 30)).save(src)
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert dest.name == "today.jpg"
    assert dest.read_bytes()[:2] == b"\xff\xd8"


def test_clean_bytes_are_upright_and_bare(tmp_path):
    src = _portrait_jpeg(tmp_path / "upload.jpg")
    img = Image.open(io.BytesIO(photo.photo_bytes_clean(src)))
    assert img.size == (80, 40)
    assert dict(img.getexif()) == {}
