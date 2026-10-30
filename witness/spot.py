"""Spot the difference: one painted era against today's photo.

A vision call picks 3 to 5 visible differences, each tied to one
verified state change quoted exactly. The child sees the verified
change line itself, never the vision model's wording. Code keeps
only differences whose grounding line is really in the research;
anything invented is dropped, several items on one change count as
one, and fewer than three grounded differences means no game.
"""

from witness.verify import filmed

MIN_DIFFERENCES = 3
MAX_DIFFERENCES = 5

DIFFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "differences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "change": {"type": "string"},
                },
                "required": ["change"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["differences"],
    "additionalProperties": False,
}


def verified_changes(scenes, claims, year) -> list:
    """One grounding line per scene from the painted era through
    today with a verified description: the scene's own supported
    claim plus a non-empty state description. Earlier scenes never
    ground a game about what changed since."""
    supported = {c.get("year") for c in claims if filmed(c)}
    lines = []
    for scene in scenes:
        scene_year = scene.get("from_year")
        description = (scene.get("state") or {}).get("description", "")
        if (isinstance(scene_year, int) and scene_year >= year
                and scene_year in supported and description.strip()):
            lines.append(f"{scene_year}: {description.strip()}")
    return lines


CONTRAST = {"ruin": 0, "burnt": 1, "demolished": 2, "damaged": 3,
              "moved": 4, "under_construction": 5, "standing": 6,
              "rebuilt": 6}


def pick_year(scenes, claims, painted) -> int | None:
    """The painted changed era that looks least like today (a ruin
    before a whole mill), earliest on ties: the starkest game."""
    supported = {c.get("year") for c in claims if filmed(c)}
    years = sorted(
        ((CONTRAST.get((s.get("state") or {}).get("condition"), 6),
          s.get("from_year")))
        for s in scenes
        if str(s.get("from_year")) in painted
        and s.get("from_year") in supported
        and (s.get("state") or {}).get("description", "").strip())
    return years[0][1] if years else None


def spot_prompt(changes) -> str:
    """Ask for visible differences, each grounded in one listed change."""
    numbered = "\n".join(f"{n}. {line}" for n, line in enumerate(changes, 1))
    return (
        "These two pictures show the same place: first a painting of "
        "how it looked in an earlier year, then a photo of today. "
        "Name 3 to 5 things that look different between the two "
        "pictures, as a child would spot them. Never name something "
        "that looks the same in both. "
        "Each difference must show one of these verified changes, "
        "and only these; quote its line exactly in \"change\":\n"
        f"{numbered}\n"
        "Never list a difference you cannot tie to one of the lines. "
        "Answer with the quoted lines only.")


def choose(vision_call, era_bytes, photo_bytes, changes):
    """Grounded differences only: the change must quote a line exactly.

    The kept entry carries the verified line itself; the vision
    wording is never shown. Drops invented and repeat groundings
    (several items on one change count as one); keeps at most five.
    Returns None when fewer than three survive or the call fails."""
    if len(changes) < MIN_DIFFERENCES:
        return None
    try:
        visions = vision_call(era_bytes, photo_bytes, spot_prompt(changes))
    except Exception:
        return None
    if not isinstance(visions, list):
        return None
    allowed = set(changes)
    kept, seen = [], set()
    for entry in visions:
        if not isinstance(entry, dict):
            continue
        change = (entry.get("change") or "").strip()
        if change not in allowed or change in seen:
            continue
        seen.add(change)
        kept.append({"change": change})
        if len(kept) == MAX_DIFFERENCES:
            break
    if len(kept) < MIN_DIFFERENCES:
        return None
    return kept


def check_game(game, scenes, claims, painted) -> bool:
    """Revalidate a stored game at render: the year is painted, 3 to 5
    distinct groundings survive, and every grounding still quotes the
    research between the game's era and today."""
    if not isinstance(game, dict):
        return False
    if game.get("year") not in [int(y) for y in painted
                                if str(y).isdigit()]:
        return False
    differences = game.get("differences")
    if not isinstance(differences, list) or len(differences) > MAX_DIFFERENCES:
        return False
    allowed = set(verified_changes(scenes, claims, game["year"]))
    grounded = set()
    for entry in differences:
        if not isinstance(entry, dict):
            return False
        change = (entry.get("change") or "").strip()
        if change not in allowed:
            return False
        grounded.add(change)
    return len(grounded) >= MIN_DIFFERENCES
