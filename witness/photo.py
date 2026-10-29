"""One clean copy of the upload.

At upload the photo is opened once, turned upright with its EXIF
orientation, stripped of all metadata and saved as today.jpg. Every later
step (vision, paint, segment, render) uses that copy, never the original.
EXIF reads (GPS, capture year) happen on the original before this runs.
"""

import io
from pathlib import Path

from PIL import Image, ImageOps


def load_clean(photo) -> Image.Image:
    """The photo upright in RGB with no metadata attached."""
    return ImageOps.exif_transpose(Image.open(photo)).convert("RGB")


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
