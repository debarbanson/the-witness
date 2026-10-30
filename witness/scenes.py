"""Step 3a: choose at most 4 scenes for a film of about 35 seconds.

State changes first, then the strongest surroundings periods, today last.
Dropped periods survive only as caption lines inside a neighbouring scene.
Pure function of the timeline and the verified claims.
"""

from witness import states
from witness.verify import refused

LIMIT = 4


def choose_scenes(timeline, claims, limit=LIMIT):
    """Pick scenes with reasons; every claim year lands in a scene or a line."""
    picked = list(timeline)
    if len(picked) > limit - 1:
        picked = _trim(picked, limit - 1)
    scenes = [
        {
            "from_year": seg["from_year"],
            "to_year": seg.get("to_year"),
            "date_label": seg.get("date_label", str(seg["from_year"])),
            "state": seg["state"],
            "reason": _reason(seg["state"]),
            "caption_lines": [],
            **({"flag": seg["flag"]} if seg.get("flag") else {}),
        }
        for seg in picked
    ]
    covered = {s["from_year"] for s in scenes}
    counts: dict = {}
    first_claim: dict = {}
    ordered = sorted(claims, key=lambda c: (c["year"], c.get("claim", "")))
    for claim in ordered:
        year = claim["year"]
        if year in covered:
            continue
        if refused(claim):
            continue
        counts[year] = counts.get(year, 0) + 1
        first_claim.setdefault(
            year, (claim.get("claim", ""), claim.get("date_text", ""), claim.get("url")))
    slots = limit - 1 - len(scenes)
    for year in sorted(counts, key=lambda y: (-counts[y], y))[: max(slots, 0)]:
        scenes.append(
            {
                "from_year": year,
                "to_year": None,
                "date_label": states.date_label(first_claim[year][1], year),
                "state": _state_at(timeline, year),
                "reason": f"{counts[year]} verified surroundings claims",
                "caption_lines": [],
            }
        )
        covered.add(year)
    scenes.sort(key=lambda s: s["from_year"])
    for year in sorted(set(first_claim) - covered):
        text, date_text, url = first_claim[year]
        dated = f"{date_text} {text}" if date_text else f"in {year} {text}"
        _nearest(scenes, year)["caption_lines"].append(
            {"year": year, "line": dated[:140], "url": url})
    scenes.append(
        {
            "from_year": "today",
            "to_year": None,
            "date_label": "today",
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


def _trim(segments, n):
    """First and last, then condition changes, then a spread of the rest.

    A visible change (ruin, rebuild, move) is what an era shows, so it
    survives trimming before another year of the same condition."""
    if n >= len(segments) or n < 2:
        return segments[: max(n, 1)]
    first, last = segments[0], segments[-1]
    middle = segments[1:-1]
    changes, rest = [], []
    for seg, prev in zip(middle, segments[:-2]):
        if seg["state"]["condition"] != prev["state"]["condition"]:
            changes.append(seg)
        else:
            rest.append(seg)
    if not changes:
        return _spread(segments, n)
    picked = [first] + changes[: n - 2]
    if len(picked) < n - 1:
        need = n - 1 - len(picked)
        picked += _spread(rest, need) if need < len(rest) else rest
    picked.append(last)
    return sorted(picked, key=segments.index)


def _state_at(timeline, year):
    """The state in a year: the open segment covering it. A description
    narrating the opening event stays at that year; only a visible
    condition travels mid-period."""
    for seg in timeline:
        to_year = seg.get("to_year")
        if seg["from_year"] <= year and (to_year is None or year < to_year):
            if year == seg["from_year"]:
                return seg["state"]
            kept = dict(seg["state"])
            if seg.get("description_from") != "visible_change":
                kept["description"] = ""
            return kept
    return {"condition": "standing", "degree": "total",
            "scope": "whole", "description": ""}


def _nearest(scenes, year):
    return min(
        (s for s in scenes if isinstance(s["from_year"], int)),
        key=lambda s: (abs(s["from_year"] - year), s["from_year"] > year),
        default=None,
    ) or scenes[-1]
