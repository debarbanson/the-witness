"""Record the live page to MP4: same render(t), stepped at 30 fps."""

import json
import subprocess
from pathlib import Path


def frame_times(duration, fps=30):
    """Frame timestamps covering the film, last frame inside the end."""
    count = max(int(duration * fps), 1)
    return [round(i / fps, 3) for i in range(count)]


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
        page.goto(film_html.as_uri())
        page.wait_for_function("typeof FILM !== 'undefined' && FILM !== null")
        for t in times:
            page.evaluate(f"render({t})")
            ffmpeg.stdin.write(page.screenshot())
        browser.close()
    ffmpeg.stdin.close()
    ffmpeg.wait()
    return out_mp4
