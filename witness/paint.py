"""Step 4: paint the verified eras with Muse Image, anchored on the photo.

Two ways to run the eras: chained (each era sees the previous turn) or
parallel (every era branches from the anchor turn alone). The model
call is injected, so tests run without live calls.
"""

import re
from concurrent.futures import ThreadPoolExecutor

SIZE = "1024x1536"  # closest accepted portrait; returns 1280x1920, cropped later
STYLE = (
    "Painterly historical illustration, soft daylight, muted period colours."
)
NO_TEXT = (
    "No text of any kind: no signs, dates, captions, signatures, "
    "watermarks or lettering."
)
MAX_REPAINTS = 2
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_SENTENCES = {
    "spring": "All eras share the anchor's spring season: fresh leaves, blossom, no snow.",
    "summer": "All eras share the anchor's summer season: leafy trees, green grass, no snow.",
    "autumn": "All eras share the anchor's autumn season: turning leaves, no snow.",
    "winter": "All eras share the anchor's winter season: bare trees, snow on the ground.",
}
CANOPY_WORDS = frozenset({"leaf", "leaves", "leafless", "bare", "crown", "canopy", "foliage"})
STOP_WORDS = frozenset({"the", "and", "for", "with", "from", "its", "into", "over"})


class PaintError(Exception):
    """A painting call failed."""


class PaintSafetyError(PaintError):
    """The safety filter blocked the scene."""


def is_safety_block(message) -> bool:
    """Any 400 that names the content policy, whatever its wording."""
    lowered = str(message).lower()
    return "content_policy" in lowered or "content management policy" in lowered


def image_tools() -> list:
    """Tool settings, proven 26 Oct (top-level parameters return 400)."""
    return [{"type": "image_generation", "size": SIZE,
             "enable_image_search": False}]


REMAINS_CONDITIONS = ("burnt", "ruin", "demolished")

# Casualties and injuries are neither visible nor paintable, and they trip
# the safety filter; the painter never sees them (film captions keep them).
HARM_WORDS = frozenset({
    "dead", "death", "deaths", "died", "dies", "dode", "doden", "dood",
    "død", "døde", "kill", "killed", "killing", "kills", "mort", "morte",
    "morts", "tot", "tote", "todes"})
HARM_STARTS = ("injur", "gewond", "bless", "victim", "casualt", "slachtoffer")


def describe_state(object_name, state) -> str:
    """The object's verified state as one paintable sentence.

    Destroyed states are framed as remains, never as the destructive
    event: the filter blocks event wording but passes aftermath.
    """
    condition = state.get("condition", "standing")
    description = (state.get("description") or "").strip()
    degree = state.get("degree") or ""
    scope = state.get("scope") or ""
    if condition in REMAINS_CONDITIONS:
        return f"Only the remains of {object_name} stand: {description}"
    if condition in ("standing", "rebuilt") and not description:
        return f"The {object_name} stands whole."
    if scope == "part":
        return f"Part of {object_name} is {condition}: {description}"
    if degree == "partial":
        return f"{object_name} is partly {condition}: {description}"
    if condition in ("standing", "rebuilt"):
        return f"The {object_name} stands {condition}: {description}"
    return f"The {object_name} is {condition}: {description}"


def scene_prompt(scene, object_name, place, season=None, excluded=()) -> str:
    """One era prompt: verified state plus verified surroundings, no
    lettering, one season unless the state governs the canopy, anchor
    elements that postdate the era kept out."""
    year = scene.get("date_label", scene.get("from_year"))
    state = scene.get("state", {})
    state_text = describe_state(object_name, state)
    surroundings = " ".join(
        line.get("line", "") for line in scene.get("caption_lines", [])
        if not _describes_harm(line.get("line", "")))
    if not surroundings.strip():
        surroundings = f"everyday life around the {place} {object_name}."
    parts = [
        f"Repaint this exact view in {place} in the year {year}, same "
        f"viewpoint, composition and painted style as the anchor photo. ",
        f"The object then: {state_text} ",
        f"Surroundings: {surroundings} ",
        f"Style: {STYLE} ",
        f"{NO_TEXT} ",
    ]
    if season in SEASON_SENTENCES and not _governs_canopy(state):
        parts.append(f"{SEASON_SENTENCES[season]} ")
    if excluded:
        parts.append(f"Do not show: {', '.join(excluded)}. ")
    parts.append("Show the object exactly as described, not as it looks today.")
    return "".join(parts)


def _describes_harm(line) -> bool:
    for token in re.findall(r"[a-zà-ÿ]+", str(line).lower()):
        if token in HARM_WORDS or token.startswith(HARM_STARTS):
            return True
    return False


def anchor_instruction(object_name, place) -> str:
    """The anchor turn: keep the viewpoint, establish the style."""
    return (
        f"This photo shows {object_name} in {place} and anchors a series "
        f"of historical illustrations of the same place. Keep its viewpoint "
        f"and composition exactly, and establish this painted style for the "
        f"series: {STYLE} {NO_TEXT}"
    )


def _governs_canopy(state) -> bool:
    """A state describing foliage overrules the series season."""
    words = set(re.findall(r"[a-z]+", str(state.get("description", "")).lower()))
    return bool(words & CANOPY_WORDS)


def anchor_report(photo_call, photo_bytes) -> dict:
    """One vision look at the anchor photo: its season plus the
    discrete temporary elements the eras must not inherit blindly."""
    answer = (photo_call(photo_bytes, ANCHOR_REPORT_PROMPT) or "").strip()
    lines = [line.strip("- *\t") for line in answer.splitlines()]
    lines = [line for line in lines if line]
    season = None
    if lines:
        first = lines[0].lower()
        for name in SEASONS:
            if name in first:
                season = name
                break
    elements = [line for line in lines[1:]
                if line.lower() not in ("none", "no elements", "n/a")]
    return {"season": season, "elements": elements}


ANCHOR_REPORT_PROMPT = (
    "Look at this photo. First line: Season: one of spring, summer, "
    "autumn, winter. Then list the discrete temporary or recent man-made "
    "elements visible (vehicles, decorations, people items, modern "
    "additions), one per line, not the weather, season, sky or landscape. "
    "If there are none, write None."
)


def element_allowed(element, texts) -> bool:
    """An anchor element may appear only where verified words name it:
    every significant word must be mentioned."""
    words = {w for w in re.findall(r"[a-zà-ÿ]+", element.lower())
             if len(w) > 2 and w not in STOP_WORDS}
    if not words:
        return True
    mentioned = set()
    for text in texts:
        mentioned.update(re.findall(r"[a-zà-ÿ]+", str(text).lower()))
    return words <= mentioned


def excluded_elements(anchor_elements, dated_texts, year) -> list:
    """Anchor elements no verified text up to `year` names. Once named,
    an element persists into later eras."""
    known = [text for when, text in dated_texts if when <= year]
    return [el for el in anchor_elements if not element_allowed(el, known)]


def paint_directives(photo_call, photo_bytes, dated_texts) -> dict:
    """The decontamination pack for a run: one season plus, per era
    year, the anchor elements that postdate it."""
    report = anchor_report(photo_call, photo_bytes)
    years = sorted({when for when, _ in dated_texts})
    return {"season": report["season"],
            "excluded": {year: excluded_elements(report["elements"], dated_texts, year)
                         for year in years}}


def extract_image_b64(response) -> str | None:
    """First generated image in a Responses payload, if any."""
    if isinstance(response, dict):
        if (response.get("type") == "image_generation_call"
                and response.get("result")):
            return response["result"]
        for value in response.values():
            found = extract_image_b64(value)
            if found:
                return found
    elif isinstance(response, list):
        for value in response:
            found = extract_image_b64(value)
            if found:
                return found
    return None


def paint_anchor(call, photo_bytes, object_name, place) -> dict:
    """The anchor turn carries the photo; eras branch from its id."""
    return call(anchor_instruction(object_name, place), None, photo_bytes)


def paint_scene(call, check_call, scene, object_name, place, prev_id,
               max_repaints=MAX_REPAINTS, photo_bytes=None, season=None,
               excluded=()) -> dict:
    """Paint one scene and check it: repaint at most twice, else drop.

    `photo_bytes` rides the first attempt only, so scene 1 needs no
    separate anchor turn.
    """
    from witness import check as check_module

    year = scene.get("from_year")
    prompt = scene_prompt(scene, object_name, place, season, excluded)
    blocks = 0
    model_retried = False
    for attempt in range(1 + max_repaints):
        try:
            result = call(prompt, prev_id,
                          photo_bytes if attempt == 0 else None)
        except PaintSafetyError:
            blocks += 1
            if blocks >= 1 + max_repaints:
                return {"year": year, "image": None, "response_id": None,
                        "verdict": "dropped", "attempts": attempt + 1,
                        "note": "safety block persists; era skipped"}
            if blocks == 1:
                continue  # flaky filter: same prompt once more
            prompt = f"{prompt} Keep the scene tasteful and non-graphic."
            continue
        except PaintError as exc:
            if model_retried:
                return {"year": year, "image": None, "response_id": None,
                        "verdict": "dropped", "attempts": attempt + 1,
                        "note": f"paint failed twice: {exc}"}
            model_retried = True
            continue
        verdict = check_module.check_painting(
            check_call, result["image"], object_name,
            describe_state(object_name, scene.get("state", {})), year)
        if verdict["verdict"] == "matches":
            return {"year": year, "image": result["image"],
                    "response_id": result["response_id"],
                    "verdict": "matches", "attempts": attempt + 1,
                    "note": verdict["note"]}
        prev_id = result["response_id"]
        prompt = (f"{scene_prompt(scene, object_name, place, season, excluded)} The previous "
                  f"attempt differed: {verdict['note']} Fix exactly that.")
    return {"year": year, "image": None, "response_id": None,
            "verdict": "dropped", "attempts": 1 + max_repaints,
            "note": verdict["note"]}


def paint_chain(call, photo_bytes, scenes, object_name, place,
                check_call=None, season=None, excluded=None) -> list:
    """Eras one after another, each chained on the previous turn."""
    anchor = paint_anchor(call, photo_bytes, object_name, place)
    prev_id = anchor["response_id"]
    out = []
    for scene in scenes:
        year_excluded = (excluded or {}).get(scene.get("from_year"), ())
        if check_call is None:
            result = call(scene_prompt(scene, object_name, place, season,
                                       year_excluded), prev_id)
            out.append({"year": scene.get("from_year"),
                        "image": result["image"],
                        "response_id": result["response_id"],
                        "verdict": "unchecked", "attempts": 1, "note": ""})
        else:
            out.append(paint_scene(call, check_call, scene, object_name,
                                   place, prev_id, season=season,
                                   excluded=year_excluded))
        if out[-1]["response_id"]:
            prev_id = out[-1]["response_id"]
    return out


def paint_parallel(call, photo_bytes, scenes, object_name, place,
                   check_call=None, max_workers=6, season=None,
                   excluded=None) -> list:
    """Every era branches from the anchor turn alone, painted at once."""
    anchor = paint_anchor(call, photo_bytes, object_name, place)
    anchor_id = anchor["response_id"]

    def one(scene):
        year_excluded = (excluded or {}).get(scene.get("from_year"), ())
        if check_call is None:
            result = call(scene_prompt(scene, object_name, place, season,
                                       year_excluded), anchor_id)
            return {"year": scene.get("from_year"), "image": result["image"],
                    "response_id": result["response_id"],
                    "verdict": "unchecked", "attempts": 1, "note": ""}
        return paint_scene(call, check_call, scene, object_name, place,
                           anchor_id, season=season, excluded=year_excluded)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(one, scenes))


def contact_sheet(panels, path, label_height=28) -> None:
    """Panels side by side with year labels, for human review."""
    from PIL import Image, ImageDraw

    from io import BytesIO
    images = [Image.open(BytesIO(raw)).convert("RGB") for _, raw in panels]
    width = sum(img.width for img in images)
    height = max(img.height for img in images) + label_height
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    x = 0
    for (label, _), img in zip(panels, images):
        sheet.paste(img, (x, label_height))
        draw.text((x + 4, 6), str(label), fill="black")
        x += img.width
    sheet.save(path)
