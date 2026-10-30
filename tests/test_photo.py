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


def test_ingest_reads_gps_cleans_and_deletes_original(tmp_path):
    from witness import identify as identify_module

    src = _portrait_jpeg(tmp_path / "upload.jpg")
    location, today = photo.ingest_upload(src, tmp_path / "job")
    assert isinstance(location, identify_module.PhotoLocation)
    assert "m" in location.precision  # a real reading, kept in memory only
    assert today.name == "today.jpg"
    assert dict(Image.open(today).getexif()) == {}
    assert not src.exists()


def test_ingest_without_gps_still_cleans_and_deletes(tmp_path):
    src = tmp_path / "upload.jpg"
    Image.new("RGB", (30, 20), (10, 200, 30)).save(src)
    location, today = photo.ingest_upload(src, tmp_path / "job")
    assert location is None
    assert today.name == "today.jpg"
    assert not src.exists()


def test_cleaning_drops_jpeg_comment(tmp_path):
    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src, comment=b"private marker")
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert Image.open(dest).info.get("comment") is None
    assert Image.open(io.BytesIO(photo.photo_bytes_clean(src))).info.get("comment") is None


def test_cleaning_drops_xmp_packet(tmp_path):
    from PIL.PngImagePlugin import PngInfo

    src = tmp_path / "upload.png"
    info = PngInfo()
    info.add_text("XML:com.adobe.xmp", "<xmp>private</xmp>")
    Image.new("RGB", (8, 8)).save(src, pnginfo=info)
    assert "XML:com.adobe.xmp" in Image.open(src).info
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert "XML:com.adobe.xmp" not in Image.open(dest).info


def test_cleaning_drops_icc_profile(tmp_path):
    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src, icc_profile=b"fakeprofile")
    assert Image.open(src).info.get("icc_profile") == b"fakeprofile"
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert Image.open(dest).info.get("icc_profile") is None


def test_cleaned_image_carries_no_info_at_all(tmp_path):
    src = _portrait_jpeg(tmp_path / "upload.jpg")
    assert photo.load_clean(src).info == {}


def test_oversize_upload_is_refused(tmp_path, monkeypatch):
    import pytest

    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src)
    monkeypatch.setattr(photo, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(photo.PhotoError):
        photo.load_clean(src)


def test_disallowed_format_is_refused(tmp_path):
    import pytest

    src = tmp_path / "upload.gif"
    Image.new("RGB", (8, 8)).save(src, format="GIF")
    with pytest.raises(photo.PhotoError):
        photo.load_clean(src)


def test_huge_dimensions_are_refused(tmp_path, monkeypatch):
    import pytest

    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src)
    monkeypatch.setattr(photo, "MAX_UPLOAD_PIXELS", 10)
    with pytest.raises(photo.PhotoError):
        photo.load_clean(src)


def test_corrupt_upload_is_refused(tmp_path):
    import pytest

    src = tmp_path / "upload.jpg"
    src.write_bytes(b"not an image at all" * 4)
    with pytest.raises(photo.PhotoError):
        photo.load_clean(src)


def test_ingest_error_still_deletes_original(tmp_path, monkeypatch):
    import pytest

    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src)

    def fail(*args):
        raise OSError("synthetic encoder failure")

    monkeypatch.setattr(photo, "prepare_photo", fail)
    with pytest.raises(OSError):
        photo.ingest_upload(src, tmp_path / "job")
    assert not src.exists()


def test_format_gate_runs_before_decode(tmp_path, monkeypatch):
    bmp = tmp_path / "x.bmp"
    Image.new("RGB", (40, 40)).save(bmp, format="BMP")
    loaded = []
    real = Image.Image.load

    def spy(self):
        loaded.append(self.format)
        return real(self)

    monkeypatch.setattr(Image.Image, "load", spy)
    import pytest

    with pytest.raises(photo.PhotoError):
        photo.load_clean(bmp)
    assert "BMP" not in loaded


def test_decoder_pixel_limit_is_ours():
    import PIL.Image

    assert PIL.Image.MAX_IMAGE_PIXELS == photo.MAX_UPLOAD_PIXELS


def test_pixel_gate_runs_before_decode(tmp_path, monkeypatch):
    import pytest

    class Huge:
        format = "JPEG"
        size = (20000, 20000)

        def load(self):
            raise AssertionError("decode must not run past the pixel gate")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("PIL.Image.open", lambda *a, **k: Huge())
    (tmp_path / "huge.jpg").write_bytes(b"\xff\xd8fake")
    with pytest.raises(photo.PhotoError) as excinfo:
        photo.load_clean(tmp_path / "huge.jpg")
    assert "pixels" in str(excinfo.value)
