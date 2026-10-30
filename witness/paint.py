"""Step 4: paint the verified eras with Muse Image, anchored on the photo.

Two ways to run the eras: chained (each era sees the previous turn) or
parallel (every era branches from the anchor turn alone). The model
call is injected, so tests run without live calls.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from witness import children, models

SIZE = "1024x1536"  # closest accepted portrait; returns 1280x1920, cropped later
STYLE = (
    "Painterly historical illustration, soft daylight, muted period colours."
)
CHILD_STYLE = (
    "Warm picture-book illustration for children, soft shapes, gentle "
    "colours, same viewpoint and composition as the anchor photo."
)
GENTLE_SCENE = (
    "Aftermath only: no flames, no smoke choking the sky, no people in "
    "danger, no frightening details."
)
NO_TEXT = (
    "No text of any kind: no signs, dates, captions, signatures, "
    "watermarks or lettering."
)
MAX_REPAINTS = 2
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_SENTENCES = {
    "spring": "The season is spring: fresh leaves, blossom, no snow.",
    "summer": "The season is summer: leafy trees, green grass, no snow.",
    "autumn": "The season is autumn: turning leaves, no snow.",
    "winter": "The season is winter: bare trees, snow on the ground.",
}
MONTHS = {
    "january": 1, "jan": 1, "januari": 1, "janvier": 1, "januar": 1,
    "enero": 1, "janeiro": 1, "gennaio": 1,
    "february": 2, "feb": 2, "februari": 2, "februar": 2, "février": 2,
    "fevrier": 2, "febrero": 2, "fevereiro": 2, "febbraio": 2,
    "march": 3, "mar": 3, "maart": 3, "märz": 3, "maerz": 3, "mars": 3,
    "marts": 3, "marzo": 3, "março": 3, "marco": 3,
    "april": 4, "apr": 4, "avril": 4, "abril": 4, "aprile": 4,
    "may": 5, "mei": 5, "mai": 5, "maj": 5, "mayo": 5, "maio": 5,
    "maggio": 5,
    "june": 6, "jun": 6, "juni": 6, "juin": 6, "junio": 6, "junho": 6,
    "giugno": 6,
    "july": 7, "jul": 7, "juli": 7, "juliol": 7, "juillet": 7,
    "julio": 7, "julho": 7, "luglio": 7,
    "august": 8, "aug": 8, "augustus": 8, "août": 8,
    "aout": 8, "agosto": 8, "augusti": 8,
    "september": 9, "sep": 9, "sept": 9, "septiembre": 9, "setembro": 9,
    "settembre": 9,
    "october": 10, "oct": 10, "oktober": 10, "octobre": 10,
    "octubre": 10, "outubro": 10, "ottobre": 10,
    "november": 11, "nov": 11, "novembre": 11, "noviembre": 11,
    "novembro": 11,
    "december": 12, "dec": 12, "dezember": 12, "décembre": 12,
    "decembre": 12, "diciembre": 12, "dezembro": 12, "dicembre": 12,
}
SEASON_WORDS = {
    "spring": "spring", "lente": "spring", "frühling": "spring",
    "frühjahr": "spring", "printemps": "spring", "forår": "spring",
    "summer": "summer", "zomer": "summer", "sommer": "summer",
    "été": "summer", "ete": "summer",
    "autumn": "autumn", "fall": "autumn", "herfst": "autumn",
    "herbst": "autumn", "automne": "autumn", "efterår": "autumn",
    "winter": "winter", "hiver": "winter", "vinter": "winter",
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

# A film never leaves one of these out while a kept painting exists.
RECOVER_CONDITIONS = ("burnt", "ruin", "damaged", "moved")

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


def scene_prompt(scene, object_name, municipality, season=None, excluded=(),
                 claims=(), audience="adult") -> str:
    """One era prompt: verified state plus verified surroundings, no
    lettering, one season unless the state governs the canopy, anchor
    elements that postdate the era kept out."""
    from witness import captions

    year = scene.get("date_label", scene.get("from_year"))
    state = scene.get("state", {})
    state_text = describe_state(object_name, state)
    surroundings = " ".join(
        line.get("line", "") for line in scene.get("caption_lines", [])
        if not _describes_harm(line.get("line", "")))
    if not surroundings.strip():
        own = [captions.claim_detail(claim) for claim in claims
               if captions.claim_matches(claim, scene.get("from_year"))
               and not _describes_harm(captions.claim_detail(claim))]
        surroundings = " ".join(own)
    if not surroundings.strip():
        surroundings = (
            f"everyday life around the {municipality} {object_name}."
            if municipality else f"everyday life around the {object_name}.")
    where = f"in {municipality} " if municipality else ""
    style = CHILD_STYLE if audience == "child" else STYLE
    parts = [
        f"Repaint this exact view {where}in the year {year}, same "
        f"viewpoint, composition and painted style as the anchor photo. ",
        f"The object then: {state_text} ",
        f"Surroundings: {surroundings} ",
        f"Style: {style} ",
        f"{NO_TEXT} ",
    ]
    if audience == "child" and state.get("condition") in children.GENTLE_CONDITIONS:
        parts.append(f"{GENTLE_SCENE} ")
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


def era_month(label) -> int | None:
    """The month named in a date label, if any: English month names
    plus the test-set languages, or an ISO date. Numeric day-first
    dates stay unread: 04/05 means April in Haarlem and May in New
    York."""
    text = (label or "").lower()
    iso = re.search(r"\d{4}-(\d{2})-\d{2}", text)
    if iso and 1 <= int(iso.group(1)) <= 12:
        return int(iso.group(1))
    for word in re.findall(r"[a-zà-ÿ]+", text):
        if word in MONTHS:
            return MONTHS[word]
    return None


def named_season(label) -> str | None:
    """A season word in a date label ("spring 2016"), if any."""
    for word in re.findall(r"[a-zà-ÿ]+", (label or "").lower()):
        if word in SEASON_WORDS:
            return SEASON_WORDS[word]
    return None


def relative_season(photo_month, photo_season, month) -> str:
    """The era's season from the photo's (month, season) pair. Both
    hemispheres advance one season per quarter from what the photo
    shows, so no hemisphere table is needed. Fallback only: camera
    clocks lie, so a known country always wins."""
    order = ["winter", "spring", "summer", "autumn"]
    steps = round(((month - photo_month) % 12) / 3) % 4
    return order[(order.index(photo_season) + steps) % 4]


# Country-level approximation: seasons turn temperate in SOUTHERN
# lands (Brazil reads southern: Rio's October is spring) and stay
# year-round in TROPICAL ones, where eras keep the anchor's season.
# Anything else reads northern.
SOUTHERN_CODES = frozenset({
    "aq", "ar", "au", "bo", "br", "bw", "ck", "cl", "fj", "ls", "mg",
    "mu", "mw", "mz", "na", "nc", "nu", "nz", "pf", "pg", "py", "sb",
    "sz", "to", "uy", "vu", "ws", "za", "zm", "zw",
})
TROPICAL_CODES = frozenset({
    "ao", "bd", "bf", "bi", "bj", "bz", "cd", "cf", "cg", "ci",
    "cm", "co", "cr", "cu", "dj", "do", "ec", "et", "ga", "gf", "gh",
    "gm", "gn", "gq", "gt", "gy", "hn", "ht", "id", "jm", "ke", "kh",
    "la", "lk", "lr", "mm", "ml", "mv", "my", "ne", "ng", "ni", "pa",
    "ph", "rw", "sg", "sl", "sn", "so", "sr", "ss", "st", "sv", "td",
    "tg", "th", "tl", "tt", "tz", "ug", "ve", "vn",
})
NORTH_MONTHS = {12: "winter", 1: "winter", 2: "winter", 3: "spring",
                4: "spring", 5: "spring", 6: "summer", 7: "summer",
                8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}


def hemisphere_season(month, country_code):
    """The season of a month in the object's country: southern order
    below the equator, nothing year-round in the tropics, northern
    order anywhere else. None when there is no month to read."""
    if month is None:
        return None
    code = (country_code or "").lower()
    if code in TROPICAL_CODES:
        return None
    season = NORTH_MONTHS[month]
    if code in SOUTHERN_CODES:
        order = ["winter", "spring", "summer", "autumn"]
        return order[(order.index(season) + 2) % 4]
    return season


def expected_season(scene, photo_month, photo_season, country_code=None):
    """An era's season: a named season in its label first, then the
    season its month implies in the object's country, then the photo
    fallback, else the anchor's season for series consistency."""
    label = scene.get("date_label", "") or ""
    named = named_season(label)
    if named is not None:
        return named
    month = era_month(label)
    if country_code:
        return hemisphere_season(month, country_code) or photo_season
    if month is not None and photo_month is not None and photo_season in SEASONS:
        return relative_season(photo_month, photo_season, month)
    return photo_season


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


def scene_caption(scene, audience="adult") -> str:
    """The scene's written caption for this audience, if it has one
    yet. No fallback: audiences never mix silently."""
    stored = scene.get("caption_sentence") or {}
    if audience == "child":
        return (stored.get("child") or {}).get("text", "")
    return stored.get("text", "")


def aftermath_prompt(scene, object_name, municipality, season=None,
                     audience="adult") -> str:
    """Last resort for remains the filter keeps blocking: the verified
    state, neutral surroundings, explicit calm negatives."""
    year = scene.get("date_label", scene.get("from_year"))
    state_text = describe_state(object_name, scene.get("state", {}))
    where = f"in {municipality} " if municipality else ""
    around = (f"everyday life around the {municipality} {object_name}. "
              if municipality else f"everyday life around the {object_name}. ")
    style = CHILD_STYLE if audience == "child" else STYLE
    parts = [
        f"Repaint this exact view {where}in the year {year}, same "
        f"viewpoint, composition and painted style as the anchor photo. ",
        f"The object then: {state_text} ",
        f"Surroundings: {around}",
        f"Style: {style} ",
        f"{NO_TEXT} ",
        "Show the morning after: quiet remains, no flames, no smoke, "
        "no people in distress. ",
    ]
    if season in SEASON_SENTENCES and not _governs_canopy(scene.get("state", {})):
        parts.append(f"{SEASON_SENTENCES[season]} ")
    parts.append("Show the object exactly as described, not as it looks today.")
    return "".join(parts)


def paint_aftermath(call, check_call, scene, object_name, municipality,
                    photo_bytes=None, season=None, max_tries=2,
                    audience="adult") -> dict:
    """One calm aftermath attempt, checked; the filter gets one retry."""
    from witness import check as check_module

    year = scene.get("from_year")
    prompt = aftermath_prompt(scene, object_name, municipality, season,
                              audience=audience)
    caption = scene_caption(scene, audience=audience)
    prev_id = None
    note = "safety block persists; era skipped"
    for attempt in range(max_tries):
        try:
            result = call(prompt, prev_id,
                          photo_bytes if prev_id is None else None)
        except PaintSafetyError:
            continue
        except Exception as exc:  # noqa: BLE001 - one failing call never kills the film
            return {"year": year, "image": None, "response_id": None,
                "caption": caption,
                    "verdict": "dropped", "attempts": attempt + 1,
                    "note": f"paint failed: {exc}"}
        try:
            verdict = check_module.check_painting(
                check_call, result["image"], object_name,
                describe_state(object_name, scene.get("state", {})), year,
                caption=caption, season=season)
        except Exception as exc:  # noqa: BLE001 - a dead check drops the era, not the film
            return {"year": year, "image": None, "response_id": None,
                "caption": caption,
                    "verdict": "dropped", "attempts": attempt + 1,
                    "note": f"check failed: {exc}"}
        if verdict["verdict"] == "matches":
            return {"year": year, "image": result["image"], "caption": caption,
                    "response_id": result["response_id"],
                    "verdict": "matches", "attempts": attempt + 1,
                    "note": verdict["note"]}
        note = verdict["note"]
        prev_id = result["response_id"]
        prompt = (f"{prompt} The previous attempt differed: {note} "
                  f"Fix exactly that.")
    return {"year": year, "image": None, "response_id": None,
        "caption": caption,
            "verdict": "dropped", "attempts": max_tries, "note": note}


def recover_scene(check_call, scene, object_name, prior,
                  audience="adult", season=None) -> dict | None:
    """Newest kept painting of a dropped critical era that passes
    today's check; None when nothing earlier survives it."""
    from witness import check as check_module

    condition = (scene.get("state") or {}).get("condition")
    if condition not in RECOVER_CONDITIONS:
        return None
    state_text = describe_state(object_name, scene.get("state", {}))
    caption = scene_caption(scene, audience=audience)
    for label, image in prior:
        verdict = check_module.check_painting(
            check_call, image, object_name, state_text,
            scene.get("from_year"), caption=caption, season=season)
        if verdict["verdict"] == "matches":
            return {"image": image, "source": label, "note": verdict["note"]}
    return None


def paint_scene(call, check_call, scene, object_name, municipality, prev_id,
               max_repaints=MAX_REPAINTS, photo_bytes=None, season=None,
               excluded=(), claims=(), audience="adult") -> dict:
    """Paint one scene and check it: repaint at most twice, else drop.

    `photo_bytes` rides the first attempt only, so scene 1 needs no
    separate anchor turn.
    """
    from witness import check as check_module

    year = scene.get("from_year")
    prompt = scene_prompt(scene, object_name, municipality, season, excluded, claims,
                          audience=audience)
    caption = scene_caption(scene, audience=audience)
    blocks = 0
    model_retried = False
    for attempt in range(1 + max_repaints):
        try:
            result = call(prompt, prev_id,
                          photo_bytes if prev_id is None else None)
        except PaintSafetyError:
            blocks += 1
            if blocks >= 1 + max_repaints:
                return {"year": year, "image": None, "response_id": None,
                    "caption": caption,
                        "verdict": "dropped", "attempts": attempt + 1,
                        "note": "safety block persists; era skipped"}
            if blocks == 1:
                continue  # flaky filter: same prompt once more
            prompt = f"{prompt} Keep the scene tasteful and non-graphic."
            continue
        except Exception as exc:  # noqa: BLE001 - timeouts retry once like model errors
            if model_retried:
                return {"year": year, "image": None, "response_id": None,
                    "caption": caption,
                        "verdict": "dropped", "attempts": attempt + 1,
                        "note": f"paint failed twice: {exc}"}
            model_retried = True
            continue
        try:
            verdict = check_module.check_painting(
                check_call, result["image"], object_name,
                describe_state(object_name, scene.get("state", {})), year,
                caption=caption, season=season)
        except Exception as exc:  # noqa: BLE001 - a dead check drops the era, not the film
            return {"year": year, "image": None, "response_id": None,
                "caption": caption,
                    "verdict": "dropped", "attempts": attempt + 1,
                    "note": f"check failed: {exc}"}
        if verdict["verdict"] == "matches":
            return {"year": year, "image": result["image"], "caption": caption,
                    "response_id": result["response_id"],
                    "verdict": "matches", "attempts": attempt + 1,
                    "note": verdict["note"]}
        prev_id = result["response_id"]
        prompt = (f"{scene_prompt(scene, object_name, municipality, season, excluded, claims, audience=audience)} "
                  f"The previous attempt differed: {verdict['note']} Fix exactly that.")
    return {"year": year, "image": None, "response_id": None,
        "caption": caption,
            "verdict": "dropped", "attempts": 1 + max_repaints,
            "note": verdict["note"]}


def paint_chain(call, photo_bytes, scenes, object_name, municipality,
                check_call=None, season=None, excluded=None,
                claims=(), audience="adult", photo_month=None,
                country_code=None) -> list:
    """Eras one after another, each chained on the previous turn. The
    first scene carries the photo; a scene with no predecessor id
    does too. A dated era takes its own season from its month in the
    object's country; undated eras share the anchor's."""
    prev_id = None
    out = []
    for scene in scenes:
        try:
            year_excluded = (excluded or {}).get(scene.get("from_year"), ())
            photo = photo_bytes if prev_id is None else None
            era_season = expected_season(scene, photo_month, season,
                                            country_code=country_code)
            if check_call is None:
                result = call(scene_prompt(scene, object_name, municipality, era_season,
                                           year_excluded, claims,
                                           audience=audience), prev_id, photo)
                out.append({"year": scene.get("from_year"),
                            "image": result["image"],
                            "response_id": result["response_id"],
                            "verdict": "unchecked", "attempts": 1, "note": ""})
            else:
                out.append(paint_scene(call, check_call, scene, object_name,
                                       municipality, prev_id, season=era_season,
                                       excluded=year_excluded, claims=claims,
                                       photo_bytes=photo, audience=audience))
        except Exception as exc:  # noqa: BLE001 - one failing call never kills the film
            out.append({"year": scene.get("from_year"), "image": None,
                        "response_id": None, "verdict": "dropped", "attempts": 1,
                        "note": f"paint crashed: {exc}"})
        if out[-1]["response_id"]:
            prev_id = out[-1]["response_id"]
    return out


def paint_parallel(call, photo_bytes, scenes, object_name, municipality,
                   check_call=None, max_workers=6, season=None,
                   excluded=None, claims=(), audience="adult",
                   photo_month=None, country_code=None) -> list:
    """The first scene carries the photo; the rest branch from its
    turn, painted at once. No spare anchor turn: its image was always
    discarded. A dated era takes its own season from its month in the
    object's country; undated eras share the anchor's."""
    if not scenes:
        return []

    def one(scene, prev_id, photo):
        try:
            year_excluded = (excluded or {}).get(scene.get("from_year"), ())
            era_season = expected_season(scene, photo_month, season,
                                            country_code=country_code)
            if check_call is None:
                result = call(scene_prompt(scene, object_name, municipality, era_season,
                                           year_excluded, claims,
                                           audience=audience), prev_id, photo)
                return {"year": scene.get("from_year"), "image": result["image"],
                        "response_id": result["response_id"],
                        "verdict": "unchecked", "attempts": 1, "note": ""}
            return paint_scene(call, check_call, scene, object_name, municipality,
                               prev_id, season=era_season, excluded=year_excluded,
                               claims=claims, photo_bytes=photo,
                               audience=audience)
        except Exception as exc:  # noqa: BLE001 - one failing call never kills the film
            return {"year": scene.get("from_year"), "image": None,
                    "response_id": None, "verdict": "dropped", "attempts": 1,
                    "note": f"paint crashed: {exc}"}

    base = one(scenes[0], None, photo_bytes)
    if len(scenes) == 1:
        return [base]
    base_id = base["response_id"]
    photo = photo_bytes if base_id is None else None
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [models.submit_context(pool, one, scene, base_id, photo)
                   for scene in scenes[1:]]
        rest = [future.result() for future in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return [base, *rest]


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
