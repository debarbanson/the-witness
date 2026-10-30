"""Step 3b: enough for a film? Never fill a gap by inventing.

Pure function of the verified claims. Interpretations pinned here:
short film needs at least 3 verified claims across at least 2 eras (more
eras never punish); fewer than 2 eras, like fewer than 3 claims, is too
little; partly means no, even with a rewrite; war-only or politics-only
claims never count.
"""

from urllib.parse import urlparse

from witness.research import is_weak_source

BUILD_WORDS = frozenset({"built", "opened", "completed"})


def decide(claims, identified) -> dict:
    """Choose full_film | short_film | too_little | not_identified."""
    if not identified:
        return _result("not_identified", 0, 0, 0, False, "object not identified")
    usable = [c for c in claims if c.get("verdict") == "supported"]
    usable = [c for c in usable if not c.get("war_politics_only")]
    verified = len(usable)
    eras = len({c["year"] for c in usable})
    good = sorted({_domain(u) for c in usable for u in c.get("sources", []) if not is_weak_source(u)})
    build_year = any((c.get("event") or "").lower() in BUILD_WORDS for c in usable)
    if verified >= 5 and eras >= 4 and len(good) >= 2 and build_year:
        return _result("full_film", verified, eras, len(good), build_year, "all thresholds met")
    if verified >= 3 and eras >= 2:
        return _result("short_film", verified, eras, len(good), build_year, "enough for a short film")
    return _result("too_little", verified, eras, len(good), build_year, "below thresholds")


def _domain(url: str) -> str:
    parts = urlparse(url).netloc.lower().removeprefix("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else url


def film_signature(film: dict) -> dict:
    """Stability metric: outcome, eras with conditions, scene years.

    Wording may differ run to run; these must not. Two films with the
    same signature are the same film for the same object.
    """
    return {
        "outcome": (film.get("outcome") or {}).get("outcome"),
        "eras": sorted(
            (seg["from_year"], seg["state"]["condition"]) for seg in film.get("timeline", [])),
        "scenes": [s["from_year"] for s in film.get("scenes", [])],
    }


def _result(outcome, verified, eras, good_sources, build_year, reason) -> dict:
    return {
        "outcome": outcome,
        "verified": verified,
        "eras": eras,
        "good_sources": good_sources,
        "build_year": build_year,
        "reason": reason,
    }
