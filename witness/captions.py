"""Adult line-2 sentences (step 7 captions).

One written first-person sentence per scene, made from that scene's own
verified claim and re-verified against its quote. Each claim is used at
most once per film; a scene with no claim of its own gets a plain line
with no fact in it. Shortening happens by rewriting, never by cutting:
no ellipsis anywhere. Model calls are injected, so tests run without
live calls.
"""

import re

from witness import states

TARGET_CHARS = 80  # what the writer aims at; fits two caption lines
MAX_CHARS = 110  # hard gate; beyond this the run fails, nothing is cut

_FIRST_PERSON = re.compile(r"\bI\b|\b[Mm]y\b")
_WRONG_VOICE = re.compile(r"\bI saw\b|\b[Ww]e\b|\b[Oo]ur\b|\b[Uu]s\b")
_YEAR = re.compile(r"\b(\d{4})\b")


def claim_matches(claim, year) -> bool:
    """A claim belongs to a scene when its year is the scene's year or
    its span covers that year."""
    if claim.get("verdict") not in ("supported", "partly"):
        return False
    if isinstance(claim.get("year"), int) and claim["year"] == year:
        return True
    span = (claim.get("from_year"), claim.get("to_year"))
    return (isinstance(span[0], int) and isinstance(span[1], int)
            and span[0] <= year <= span[1])


def claim_detail(claim) -> str:
    """The claim's own words: the narrowed rewrite when one exists."""
    return claim.get("rewritten") or claim.get("claim", "")


def assign_claims(scenes, claims) -> dict:
    """One claim per painted scene in film order, each claim used once.
    When several match, the most informative (longest detail) tells the
    scene's story."""
    assigned = {}
    used = set()
    for scene in scenes:
        year = scene.get("from_year")
        if not isinstance(year, int):
            continue
        if states.is_age_range(scene.get("date_label", "")):
            continue
        matching = [index for index, claim in enumerate(claims)
                    if index not in used and claim_matches(claim, year)]
        if not matching:
            continue
        best = max(matching,
                   key=lambda i: (len(claim_detail(claims[i])), -i))
        assigned[year] = claims[best]
        used.add(best)
    return assigned


def sentence_prompt(detail, quote, year) -> str:
    """One first-person sentence from the source, no years, no cutting."""
    return (
        "You are the object itself (the mill, the tree, the lighthouse). "
        "Write one first-person sentence for a museum film caption about "
        f"the year {year}: I or my, never I saw, we or our. "
        "For the object's parts or buildings, say my (my sails, my buildings). "
        "Cover the claim's main event; if the source gives an age, include it. "
        "Say only what the source sentence says, no more. "
        "Do not mention any year or date; the film already shows the year. "
        f"At most {TARGET_CHARS} characters, never cut off mid-word. "
        f"Source: {quote} Claim: {detail}")


def sentence_ok(sentence, year) -> bool:
    """Code gate: first person, own year at most, fits, never cut."""
    if not sentence or "…" in sentence or len(sentence) > MAX_CHARS:
        return False
    if not _FIRST_PERSON.search(sentence):
        return False
    if _WRONG_VOICE.search(sentence):
        return False
    return all(int(found) == year for found in _YEAR.findall(sentence))


def write_sentence(rewrite_call, support_call, claim, year) -> dict:
    """Rewrite plus re-verification; shorter retry once, else failure."""
    detail = claim_detail(claim)
    for attempt, plain in enumerate((False, True), 1):
        sentence = (rewrite_call(detail, claim.get("quote", ""), year, plain)
                    or "").strip()
        if (sentence and sentence_ok(sentence, year)
                and support_call(sentence, claim.get("quote", ""))
                in ("supported", "partly")):
            return {"sentence": sentence, "verified": True, "attempts": attempt}
    return {"sentence": None, "verified": False, "attempts": 2}


def fallback_line(scene) -> str:
    """A plain first-person line with no fact, distinct per scene."""
    year = scene["from_year"]
    if not isinstance(year, int):
        raise KeyError(f"no fallback for a {year!r} scene")
    condition = (scene.get("state") or {}).get("condition", "standing")
    if condition == "standing":
        return f"Here I stood in {year}, much as always."
    if condition == "rebuilt":
        return f"Here I stood in {year}, whole again."
    if condition == "moved":
        return f"Here I stood in {year}, in my new place."
    return f"Here I stood in {year}, as you see me."
