"""The film as a stream: opening card, scene events, buffer rule.

Nothing is shown until it is verified, and nothing shown is ever
withdrawn or changed. Within that rule the film plays like a video
stream: an opening card over the user's own photo within seconds,
then one ready scene after another, with playback starting as soon
as the remaining build time fits inside the remaining viewing time.
"""

import threading
import time


def build_year_from_claims(claims):
    """Earliest Wikidata-anchored build year, or None when no anchor."""
    anchored = [c["year"] for c in claims if c.get("anchor") == "build"]
    return min(anchored) if anchored else None


def opening_card(name, kind, claims):
    """The opening card: name, kind and the verified build year only.

    The year comes from Wikidata and is already verified, so the card
    needs no model call. Without an anchor the year line is omitted,
    never guessed. The card names no photo: the stream is saved to
    research.json, and local paths are personal data.
    """
    since_year = build_year_from_claims(claims)
    return {
        "event": "opening_card",
        "name": name,
        "kind": kind,
        "since_year": since_year,
        "text": f"I have stood here since {since_year}." if since_year else None,
    }


def scene_event(scene_no, scene, image, elapsed):
    """A scene is ready: number, year, captions, source and image."""
    return {
        "event": "scene_ready",
        "scene": scene_no,
        "year": scene["from_year"],
        "date_label": scene.get("date_label", str(scene["from_year"])),
        "state": scene["state"],
        "caption_lines": scene["caption_lines"],
        "image": image,
        "t": elapsed,
    }


def newly_ready_scenes(draft, judged_years, to_check_years, emitted,
                       supported_years):
    """Draft scenes whose every checked claim is judged, minus emitted.

    `judged_years` and `to_check_years` are year multisets (one entry
    per claim); a scene year is ready when judged covers checked and
    at least one of its claims came back supported.
    """
    remaining = {}
    for year in to_check_years:
        remaining[year] = remaining.get(year, 0) + 1
    for year in judged_years:
        if year in remaining:
            remaining[year] -= 1
    supported = {}
    for year in supported_years:
        supported[year] = supported.get(year, 0) + 1
    return [s for s in draft
            if isinstance(s["from_year"], int)
            and remaining.get(s["from_year"], 0) <= 0
            and supported.get(s["from_year"], 0) > 0
            and s["from_year"] not in emitted]


def scene_numbers(draft) -> dict:
    """Scene numbers follow film order, never completion order."""
    return {s["from_year"]: n for n, s in enumerate(draft, 1)}


def buffer_ready(scenes_total, scenes_ready, elapsed, scene_seconds=7):
    """Playback starts when the remaining build fits in the play time.

    The build rate is measured, not guessed: elapsed time over scenes
    ready so far. Like video buffering: scene 1 plays while the rest
    still builds, and the film never stalls.
    """
    if scenes_ready <= 0:
        return False
    if scenes_ready >= scenes_total:
        return True
    per_scene = elapsed / scenes_ready
    return (scenes_total - scenes_ready) * per_scene <= scenes_total * scene_seconds


def simulate_playback(ready, scene_seconds=7):
    """Would playback ever pause? Scenes play in film order from the
    moment the buffer rule first holds; any scene not ready when its
    slot starts is a pause. `ready` is (year, seconds) in film order;
    the closing "today" slot needs no build and never pauses.
    """
    total = len(ready)
    if not total:
        return {"start": None, "pauses": []}
    build = sorted((when for year, when in ready if year != "today"))
    start = build[-1] if build else 0.0
    for done, when in enumerate(build, 1):
        if buffer_ready(total, done, when, scene_seconds):
            start = when
            break
    pauses = [year for i, (year, when) in enumerate(ready)
              if when > start + i * scene_seconds]
    return {"start": start, "pauses": pauses}


def simulate_paint_shop(verified, paint_seconds=33, workers=6):
    """Painted-ready times from verified times in completion order.

    Each scene takes one worker for `paint_seconds` (measured mean
    paint plus check); a scene starts when verified and a worker is
    free. Returns {year: ready seconds}.
    """
    free_at = [0.0] * max(workers, 1)
    ready = {}
    for year, when in verified:
        slot = min(range(len(free_at)), key=lambda i: free_at[i])
        start = max(when, free_at[slot])
        free_at[slot] = round(start + paint_seconds, 1)
        ready[year] = free_at[slot]
    return ready


def confirm_speculative(prompt, begin, decide):
    """Start `begin` in the background, then ask `decide`.

    The user's hesitation becomes free work time: research and anchor
    checks run while they look at the confirm screen. On no the
    result is thrown away; on yes it is awaited and kept.
    """
    box: dict = {}

    def work():
        try:
            box["result"] = begin()
        except Exception as exc:  # noqa: BLE001 - speculative; caller retries cleanly
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    if not decide():
        return False, None
    thread.join()
    if "error" in box:
        raise box["error"]
    return True, box.get("result")


class FilmStream:
    """Timestamped event log plus the three delivery metrics."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self.events = []

    def elapsed(self):
        return round(time.perf_counter() - self.t0, 1)

    def emit(self, event, data=None):
        entry = {"event": event, "t": self.elapsed()}
        if data:
            entry.update(data)
        self.events.append(entry)
        return entry

    def metric(self, event):
        """Seconds to the first event of a type, or None."""
        for entry in self.events:
            if entry["event"] == event:
                return entry["t"]
        return None
