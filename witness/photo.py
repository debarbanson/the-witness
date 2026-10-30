"""One clean copy of the upload.

At upload the photo is gated (bytes, format, pixels), opened once,
turned upright with its EXIF orientation, and its pixels are copied
into a fresh image with no metadata at all: no EXIF, XMP, ICC or
comment. Every later step (vision, paint, segment, render) uses that
copy, never the original. EXIF reads (GPS, capture year) happen on
the original before this runs.
"""

import io
from pathlib import Path

from PIL import Image, ImageOps


class PhotoError(Exception):
    """The upload is missing, too big, the wrong shape or unreadable."""


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB per upload
MAX_UPLOAD_PIXELS = 100_000_000  # 100 MP covers phone panos
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


def load_clean(photo) -> Image.Image:
    """The photo upright in RGB on a fresh canvas: pixels only, an
    empty info dict, nothing inherited from the file."""
    try:
        data = Path(photo).read_bytes()
    except OSError as exc:
        raise PhotoError(f"unreadable upload: {exc.__class__.__name__}")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError(f"upload too large ({len(data)} bytes)")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            found, size = img.format, img.size
            upright = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:
        raise PhotoError(f"unreadable upload: {exc.__class__.__name__}")
    if found not in ALLOWED_FORMATS:
        raise PhotoError(f"upload must be JPEG, PNG or WebP, not {found}")
    if size[0] * size[1] > MAX_UPLOAD_PIXELS:
        raise PhotoError(f"upload too many pixels ({size[0]}x{size[1]})")
    fresh = Image.new("RGB", upright.size)
    fresh.paste(upright)
    return fresh


def prepare_photo(photo, dest_dir) -> Path:
    """Save the clean copy as today.jpg under dest_dir; return its path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "today.jpg"
    load_clean(photo).save(dest, quality=92)
    return dest


def photo_bytes_clean(photo) -> bytes:
    """Clean JPEG bytes for API calls that take image bytes."""
    buf = io.BytesIO()
    load_clean(photo).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def ingest_upload(src, job_dir):
    """Take a web upload: read its GPS first, lay the clean today.jpg,
    then delete the original with its location. Returns (location or
    None, today.jpg path). The location stays in memory for the lookup
    and is never written anywhere. The original is deleted on every
    path, including errors."""
    from witness import identify as identify_module

    src = Path(src)
    try:
        try:
            location = identify_module.read_location(src)
        except identify_module.NoGpsError:
            location = None
        today = prepare_photo(src, job_dir)
    finally:
        src.unlink(missing_ok=True)
    return location, today
