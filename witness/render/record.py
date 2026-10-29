"""Record the live page to MP4: same render(t), stepped at 30 fps."""

import json
import subprocess
from pathlib import Path


def frame_times(duration, fps=30):
    """Frame timestamps covering the film, last frame inside the end."""
    count = max(int(duration * fps), 1)
    return [round(i / fps, 3) for i in range(count)]


def page_url(film_html) -> str:
    """Fixed-frame URL: the page renders t=0 once and starts no clock,
    so the recorder owns every frame."""
    return Path(film_html).resolve().as_uri() + "?t=0"


READY_JS = "window.__READY === true"
FRAME_JS = ("[...document.querySelectorAll('#stage img')]"
            ".filter(i => i.src)"
            ".every(i => i.complete && i.naturalWidth > 0)")


def finish_ffmpeg(proc):
    """Close the pipe and fail loudly when ffmpeg did."""
    proc.stdin.close()
    code = proc.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, "ffmpeg")
    return code


def edges_lit(frame, width=100, threshold=12) -> bool:
    """The leftmost and rightmost columns hold picture, not black bars."""
    grey = frame.convert("L")
    w, h = grey.size
    left = grey.crop((0, 0, min(width, w), h))
    right = grey.crop((max(w - width, 0), 0, w, h))
    pixels = list(left.getdata()) + list(right.getdata())
    return sum(pixels) / len(pixels) > threshold


def record(film_html, out_mp4, fps=30):
    """Playwright steps render(t); ffmpeg encodes H.264 1080x1920."""
    from playwright.sync_api import sync_playwright

    film_html = Path(film_html).resolve()
    film = json.loads((film_html.parent / "film.json").read_text())
    duration = film["segments"][-1]["end"]
    times = frame_times(duration, fps)
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "image2pipe", "-framerate", str(fps),
         "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out_mp4)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 540, "height": 960},
                                device_scale_factor=2)
        page.goto(page_url(film_html))
        page.wait_for_function(READY_JS)
        for t in times:
            page.evaluate(f"render({t})")
            page.wait_for_function(FRAME_JS)
            ffmpeg.stdin.write(page.screenshot())
        browser.close()
    finish_ffmpeg(ffmpeg)
    return out_mp4
