"""Step 4: paint the verified eras with Muse Image, anchored on the photo.

Two ways to run the eras: chained (each era sees the previous turn) or
parallel (every era branches from the anchor turn alone). The model
call is injected, so tests run without live calls.
"""

from concurrent.futures import ThreadPoolExecutor

SIZE = "1024x1536"  # closest accepted portrait; returns 1280x1920, cropped later
STYLE = (
    "Painterly historical illustration, soft daylight, muted period colours."
)
MAX_REPAINTS = 2


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


def scene_prompt(scene, object_name, place) -> str:
    """One era prompt: verified state plus verified surroundings."""
    year = scene.get("date_label", scene.get("from_year"))
    state_text = describe_state(object_name, scene.get("state", {}))
    surroundings = " ".join(line.get("line", "")
                            for line in scene.get("caption_lines", []))
    if not surroundings.strip():
        surroundings = f"everyday life around the {place} {object_name}."
    return (
        f"Repaint this exact view in {place} in the year {year}, same "
        f"viewpoint, composition and painted style as the anchor photo. "
        f"The object then: {state_text} "
        f"Surroundings: {surroundings} "
        f"Style: {STYLE} "
        f"Show the object exactly as described, not as it looks today."
    )


def anchor_instruction(object_name, place) -> str:
    """The anchor turn: keep the viewpoint, establish the style."""
    return (
        f"This photo shows {object_name} in {place} and anchors a series "
        f"of historical illustrations of the same place. Keep its viewpoint "
        f"and composition exactly, and establish this painted style for the "
        f"series: {STYLE}"
    )


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
               max_repaints=MAX_REPAINTS) -> dict:
    """Paint one scene and check it: repaint at most twice, else drop."""
    from witness import check as check_module

    year = scene.get("from_year")
    prompt = scene_prompt(scene, object_name, place)
    softened = False
    model_retried = False
    for attempt in range(1 + max_repaints):
        try:
            result = call(prompt, prev_id)
        except PaintSafetyError:
            if softened:
                return {"year": year, "image": None, "response_id": None,
                        "verdict": "dropped", "attempts": attempt + 1,
                        "note": "safety block twice; era skipped"}
            prompt = f"{prompt} Keep the scene tasteful and non-graphic."
            softened = True
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
            describe_state(object_name, scene.get("state", {})))
        if verdict["verdict"] == "matches":
            return {"year": year, "image": result["image"],
                    "response_id": result["response_id"],
                    "verdict": "matches", "attempts": attempt + 1,
                    "note": verdict["note"]}
        prev_id = result["response_id"]
        prompt = (f"{scene_prompt(scene, object_name, place)} The previous "
                  f"attempt differed: {verdict['note']} Fix exactly that.")
    return {"year": year, "image": None, "response_id": None,
            "verdict": "dropped", "attempts": 1 + max_repaints,
            "note": verdict["note"]}


def paint_chain(call, photo_bytes, scenes, object_name, place,
                check_call=None) -> list:
    """Eras one after another, each chained on the previous turn."""
    anchor = paint_anchor(call, photo_bytes, object_name, place)
    prev_id = anchor["response_id"]
    out = []
    for scene in scenes:
        if check_call is None:
            result = call(scene_prompt(scene, object_name, place), prev_id)
            out.append({"year": scene.get("from_year"),
                        "image": result["image"],
                        "response_id": result["response_id"],
                        "verdict": "unchecked", "attempts": 1, "note": ""})
        else:
            out.append(paint_scene(call, check_call, scene, object_name,
                                   place, prev_id))
        if out[-1]["response_id"]:
            prev_id = out[-1]["response_id"]
    return out


def paint_parallel(call, photo_bytes, scenes, object_name, place,
                   check_call=None, max_workers=6) -> list:
    """Every era branches from the anchor turn alone, painted at once."""
    anchor = paint_anchor(call, photo_bytes, object_name, place)
    anchor_id = anchor["response_id"]

    def one(scene):
        if check_call is None:
            result = call(scene_prompt(scene, object_name, place), anchor_id)
            return {"year": scene.get("from_year"), "image": result["image"],
                    "response_id": result["response_id"],
                    "verdict": "unchecked", "attempts": 1, "note": ""}
        return paint_scene(call, check_call, scene, object_name, place,
                           anchor_id)

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
