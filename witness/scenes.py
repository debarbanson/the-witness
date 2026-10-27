"""Step 3a: choose at most 7 scenes for a 40 to 60 second film.

State changes first, then the strongest surroundings periods, today last.
Dropped periods survive only as caption lines inside a neighbouring scene.
Pure function of the timeline and the verified claims.
"""

LIMIT = 7


def choose_scenes(timeline, claims, limit=LIMIT):
    """Pick scenes with reasons; every claim year lands in a scene or a line."""
    picked = list(timeline)
    if len(picked) > limit - 1:
        picked = _spread(picked, limit - 1)
    scenes = [
        {
            "from_year": seg["from_year"],
            "to_year": seg.get("to_year"),
            "state": seg["state"],
            "reason": _reason(seg["state"]),
            "caption_lines": [],
        }
        for seg in picked
    ]
    covered = {s["from_year"] for s in scenes}
    counts: dict = {}
    first_claim: dict = {}
    for claim in claims:
        year = claim["year"]
        if year in covered:
            continue
        counts[year] = counts.get(year, 0) + 1
        first_claim.setdefault(year, (claim.get("claim", ""), claim.get("date_text", "")))
    slots = limit - 1 - len(scenes)
    for year in sorted(counts, key=lambda y: (-counts[y], y))[: max(slots, 0)]:
        scenes.append(
            {
                "from_year": year,
                "to_year": None,
                "state": _state_at(timeline, year),
                "reason": f"{counts[year]} verified surroundings claims",
                "caption_lines": [],
            }
        )
        covered.add(year)
    scenes.sort(key=lambda s: s["from_year"])
    for year in sorted(set(first_claim) - covered):
        text, date_text = first_claim[year]
        dated = f"{date_text} {text}" if date_text else f"in {year} {text}"
        _nearest(scenes, year)["caption_lines"].append({"year": year, "line": dated[:140]})
    scenes.append(
        {
            "from_year": "today",
            "to_year": None,
            "state": {"condition": "standing", "degree": "total",
                      "scope": "whole", "description": ""},
            "reason": "closing on the user's photo",
            "caption_lines": [],
        }
    )
    return scenes


def _reason(state: dict) -> str:
    reason = f"object changed state ({state['condition']})"
    if state.get("description"):
        reason += f": {state['description']}"
    return reason[:140]


def _spread(items, n):
    """First, last and evenly spread middle items."""
    if n >= len(items) or n < 2:
        return items[: max(n, 1)]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def _state_at(timeline, year):
    for seg in timeline:
        to_year = seg.get("to_year")
        if seg["from_year"] <= year and (to_year is None or year < to_year):
            return seg["state"]
    return {"condition": "standing", "degree": "total",
            "scope": "whole", "description": ""}


def _nearest(scenes, year):
    return min(
        (s for s in scenes if isinstance(s["from_year"], int)),
        key=lambda s: (abs(s["from_year"] - year), s["from_year"] > year),
        default=None,
    ) or scenes[-1]
