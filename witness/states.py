"""What the object looks like in a year.

A state is a condition from a fixed list plus degree, scope and a free
sourced description of the visible change. One meaning question decides
state vs caption: does this change what the object physically looks
like? Anything else is a caption, never a state or a scene. There are
no lists of excluded event names or properties; depiction, plans and
non-physical history fall out by meaning.
"""

import re

CONDITIONS = (
    "under_construction",
    "standing",
    "damaged",
    "burnt",
    "ruin",
    "rebuilt",
    "moved",
    "demolished",
)
DEGREES = ("partial", "total")
SCOPES = ("whole", "part")

# A depiction of the object is not a change to it.
DEPICT_WORDS = ("image", "images", "photo", "photograph", "depicts", "depiction", "portrait")

# Planned, promised or failed changes that never happened. Completion
# words rescue them ("rebuild planned; first pole in the ground").
INCOMPLETE_WORDS = (
    "planned", "proposed", "considered", "prevented", "averted", "called off",
    "failed", "failure", "oblivion", "nothing happened", "never happened",
)
COMPLETION_WORDS = (
    "start", "started", "begin", "began", "begun", "complete", "completed",
    "completion", "finished", "opened", "built", "rebuilt", "put in",
    "underway", "under way", "first stone", "first pole", "foundation stone",
    "cornerstone", "commenced", "carried out", "delivered", "begonnen",
    "gestart", "eerste steen", "eerste paal",
)

# Detached structures, surroundings and interiors are never the object
# itself. Surroundings always veto a state; interiors veto unless the
# event is constructive ("rebuilt: restaurant pavilions renewed" still
# describes work on the object). Attached parts read on the whole object
# when changed constructively ("wings completed" extends it); with
# destructive events they keep a part-scoped state for damage the object
# survives, and become captions when the part is gone.
SURROUNDINGS = (
    "outbuilding", "annex", "bijgebouw", "dependance", "shed", "garage",
    "small building", "fence", "outlying", "ancillary", "surrounding",
)
INTERIOR = (
    "interior", "foyer", "lobby", "room", "ballroom", "restaurant",
    "entrance", "door", "doorway",
)
CONTENTS = (
    "exhibition", "collection", "furniture", "archive", "archives",
    "holdings", "artefact", "artifact", "throne",
    "sculptures", "reliefs", "carvings", "relics", "murals", "frescoes",
    "inscriptions",
)
OCCUPANTS = (
    "assembly", "parliament", "council", "committee", "government",
    "tenant", "resident", "occupant", "household", "staff",
    "museum", "school", "congregation", "company", "capital", "court",
)
RULERS = ("king", "queen", "emperor", "empress", "ruler", "monarch")
SEATS = ("capital", "court", "throne", "seat", "palace", "residence", "castle", "manor")
ATTACHED_PART = (
    "wing", "vleugel", "branch", "deck", "track", "rail", "cable",
    "span", "roadway", "chimney", "lift", "elevator", "escalator", "staircase",
    "barracks", "barrack", "stables",
)
DESTRUCTIVE_WORDS = (
    "demolish", "destroy", "burn", "damage", "remove", "torn down",
    "collapse", "wash away",
)

TOTAL_WORDS = ("completely", "totally", "entirely", "wholly", "fully", "gutted",
               "volledig", "geheel", "helemaal")
PARTIAL_WORDS = ("partly", "partially", "gedeeltelijk")
NEGATIONS = ("never", "not", "no", "without", "geen", "niet", "nooit")

RUIN_WORDS = (
    "burnt down", "burned down", "to the ground", "destroy", "conflagration",
    "washed away", "swept away", "collaps", "afgebrand", "platgebrand",
    "verwoest", "ingestort",
)
FIRE_WORDS = ("fire", "fires", "burnt", "burned", "burning", "brand", "blaze", "flames")
DEMOLISH_WORDS = (
    "demolish", "torn down", "tore down", "pulled down", "dismantled",
    "razed", "sloop", "gesloopt", "afgebroken",
)
MOVE_WORDS = ("moved", "relocation", "relocated", "verplaatst")
REBUILD_WORDS = ("rebuilt", "reconstructed", "reconstruction", "rebuilding", "reopened", "herbouw")
START_WORDS = (
    "started", "underway", "under way", "work began", "work started",
    "construction began", "construction started", "began construction",
    "started construction", "first stone", "first pole",
    "begonnen", "eerste steen", "eerste paal",
)
# A foundation stone is a ceremony; the object has no visible form yet.
FOUNDATION_WORDS = ("foundation stone", "cornerstone")
# Survival counter-evidence: the form outlived the destruction.
SURVIVED_WORDS = ("surviv", "remain", "still standing", "left standing", "leaving just")
COMPLETED_WORDS = ("completed", "completion", "finished", "delivered")
# Fire prevention is not fire.
INNOCENT_PHRASES = (
    "fire-retardant", "fire retardant", "fire-resistant", "fire resistant",
    "fireproof", "fire protection", "against fire", "fire safety",
)
# Event words that carry the verdict on what this change was. Detail
# words that contradict them describe means or context ("reconstructed
# promenade", "palace pulled down"), not the change.
EVENT_ALTER = (
    "extended", "extension", "enlarged", "enlargement", "widened",
    "widening", "heightened", "raised", "lengthened", "replaced", "renewed",
)
EVENT_RESTORE = (
    "restored", "restoration", "renovated", "renovation", "refurbished",
    "refurbishment", "repaired", "repainted",
)
EVENT_STANDING = (
    "built", "opened", "completed", "inaugurated", "erected", "unveiled",
)
EVENT_CONSTRUCT = ("construction",)
EVENT_REBUILD = ("rebuilt", "reconstructed", "reopened", "reconstruction", "rebuilding")
EVENT_MOVE = ("moved", "relocated", "relocation")
CONSTRUCT_START = (
    "construction began", "construction started", "began construction",
    "started construction", "start bouw", "begin bouw", "bouw begonnen",
    "in aanbouw", "under construction",
)
CONSTRUCTIVE_EVENTS = (EVENT_ALTER + EVENT_RESTORE + EVENT_STANDING
                       + EVENT_CONSTRUCT + EVENT_REBUILD)
STANDING_WORDS = (
    "built", "opened", "completed", "inaugurated", "finished", "erected",
    "unveiled", "end of construction", "taken into use", "in use",
    "taken into service", "in service", "first lit", "lit for the first time",
    "first turned on",
    "gebouwd", "geopend", "voltooid", "opgericht", "opgeleverd", "onthuld",
)
RESTORE_WORDS = (
    "restor", "renovat", "refurbish", "redecorat", "repair", "repaint",
    "whitewash", "opgeknapt", "gerestaureerd", "gerenoveerd",
)
ALTER_WORDS = (
    "extended", "extension", "enlarged", "enlargement", "heightened",
    "height raised", "raised by", "taller", "new storey", "steam engine",
    "steam mill", "steam-powered", "stoom", "replac", "renew", "pollard",
    "uitgebreid", "vergroot", "verhoogd", "vervangen", "vernieuwd",
)
DAMAGE_WORDS = (
    "damag", "storm", "lightning", "vandal", "crack", "flood", "broken",
    "snapped", "bliksem", "beschadigd", "vernield", "struck by lightning",
)
FINAL_WORDS = tuple(w for w in STANDING_WORDS if w not in ("built", "gebouwd"))


def _has(text: str, words) -> str | None:
    """First whole word or phrase found, else None."""
    for word in words:
        if " " in word:
            if word in text:
                return word
        elif re.search(rf"\b{re.escape(word)}\w*\b", text):
            return word
    return None


def _negated(text: str, word: str) -> bool:
    """A negation shortly before the match ("never burnt down")."""
    at = text.find(word)
    before = text[max(0, at - 30):at]
    return bool(re.search(rf"\b({'|'.join(NEGATIONS)})\b[\w\s]*$", before))


def _nearly_destroyed(text: str) -> bool:
    """Near destruction ("near-destroyed", "almost burnt down"). Bare
    "near" is a place, and "almost a year" is a duration: both need the
    destruction words close by."""
    if "near-" in text:
        return True
    return bool(re.search(
        r"\b(nearly|almost|virtually)\b.{0,15}\b(destroy|burn|collaps|demolish|wreck)", text))


def _constructing(text: str) -> bool:
    """Construction stated as ongoing, unless completion is stated too."""
    if _has(text, FINAL_WORDS):
        return False
    if _has(text, CONSTRUCT_START):
        return True
    return "construction" in text and bool(re.search(r"\bbeg[au]n\b|\bstarted\b", text))


def _occupant_moved(event: str, detail: str) -> bool:
    """The thing moving is contents or occupants, not the object.

    A ruler with a seat of power ("the king moved the capital")
    is never the object; ship names ("Queen Mary") need the seat
    too, so they keep their genuine moves. Otherwise position
    decides: occupant words before the move word are the subject
    ("the congregation moved"), "moved X" names what moved, and
    only "moved to X" names a destination. When the move is
    stated by the event alone, a named occupant in the detail
    moved.
    """
    lowered = f"{event} {detail}".lower().replace("courthouse", "civic building")
    if _has(lowered, RULERS) and _has(lowered, SEATS):
        return True
    if not (_has(lowered, CONTENTS) or _has(lowered, OCCUPANTS)):
        return False
    said = detail.lower().replace("courthouse", "civic building")
    hits = [m.start() for pat in MOVE_WORDS
            for m in re.finditer(rf"\b{re.escape(pat)}\w*\b", said)]
    if not hits:
        return True
    first = min(hits)
    if _has(said[:first], CONTENTS) or _has(said[:first], OCCUPANTS):
        return True
    after = said[first:]
    for word in CONTENTS + OCCUPANTS:
        for match in re.finditer(rf"\b{re.escape(word)}\w*\b", after):
            between = after[: match.start()]
            if re.search(r"[;.,]", between):
                continue  # a new clause names something else
            if not re.search(r"\b(to|into|onto)\b", between):
                return True
    return False


def _destruction_stated(text: str) -> bool:
    """Unnegated destruction words: the change follows real damage."""
    for words in (RUIN_WORDS, DEMOLISH_WORDS, DAMAGE_WORDS, FIRE_WORDS):
        hit = _has(text, words)
        if hit and not _negated(text, hit):
            return True
    return False


def looks_incomplete(event: str, detail: str = "", visible_change: str = "") -> bool:
    """The text raises doubt: planned, promised or failed change without
    completion words. Completion is asked exactly then. Completion must
    come from what the sources say (detail), never from the event label
    vouching for itself."""
    text = f"{event} {detail} {visible_change}".lower()
    said = f"{detail} {visible_change}".lower()
    incomplete = _has(text, INCOMPLETE_WORDS)
    return bool(incomplete) and not _negated(text, incomplete) and not _has(said, COMPLETION_WORDS)


def scope_of(event: str, detail: str = "") -> str:
    """Whole (the object itself) or part (an outbuilding, a wing)."""
    text = f"{event} {detail}".lower()
    if _has(text, SURROUNDINGS) or _has(text, INTERIOR):
        return "part"
    if _has(text, ATTACHED_PART) and _has(text, DESTRUCTIVE_WORDS):
        return "part"
    return "whole"


def classify(event: str, detail: str = "", visible_change: str = "",
             previous: str | None = None) -> dict | None:
    """Meaning classification: a state dict, or None for caption only.

    `previous` is the condition of the preceding segment, so a facelift
    after standing ("rebuilt" meaning redecorated) is not mistaken for
    a genuine rebuild after ruin.
    """
    text = f"{event} {detail} {visible_change}".lower()
    for phrase in INNOCENT_PHRASES:
        text = text.replace(phrase, " ")
    for prior in ("remain intact", "remained intact", "remaining intact"):
        text = text.replace(prior, " ")
    words = set(re.findall(r"[a-z]+", event.lower()))
    if _has(" ".join(sorted(words)), DEPICT_WORDS):
        return None
    if looks_incomplete(event, detail, visible_change):
        return None
    if _has(f"{detail} {visible_change}".lower(), FOUNDATION_WORDS) and not _has(text, FINAL_WORDS):
        return None
    constructive = bool(words & set(CONSTRUCTIVE_EVENTS))
    lowered = f"{event} {detail}".lower()
    if _has(lowered, SURROUNDINGS):
        return None
    if _has(lowered, INTERIOR) and not constructive:
        return None
    description = visible_change.strip() or " ".join(detail.split())[:140]

    def state(condition, degree="total", scope="whole"):
        return {"condition": condition, "degree": degree,
                "scope": scope, "description": description}

    if words & set(EVENT_ALTER):
        return state("standing")
    if words & set(EVENT_RESTORE):
        if _has(text, START_WORDS):
            return state("under_construction")
        return state("standing")
    if words & set(EVENT_STANDING):
        if _constructing(text):
            return state("under_construction")
        return state("standing")
    if words & set(EVENT_CONSTRUCT):
        if _has(text, FINAL_WORDS):
            return state("standing")
        return state("under_construction")
    if words & set(EVENT_REBUILD):
        if _has(text, START_WORDS):
            return state("under_construction")
        if (previous == "standing" and not _has(text, COMPLETED_WORDS)
                and not _destruction_stated(text)):
            return state("standing")  # a facelift, not a rebuild after ruin
        return state("rebuilt")
    if words & set(EVENT_MOVE):
        if _occupant_moved(event, detail):
            return None  # contents or occupants moved; the object stayed
        return state("moved")
    part = _has(lowered, ATTACHED_PART) and _has(text, DESTRUCTIVE_WORDS)
    ruin = _has(text, RUIN_WORDS)
    if ruin and not _negated(text, ruin):
        if part:
            return None  # the part is gone; the object remains
        if _has(text, PARTIAL_WORDS) or _nearly_destroyed(text):
            if _has(text, FIRE_WORDS):
                return state("burnt", "partial")
            return state("damaged", "partial")
        if _has(text, SURVIVED_WORDS):
            if _has(text, FIRE_WORDS):
                return state("burnt", "partial")
            return state("damaged", "partial")
        return state("ruin")
    fire = _has(text, FIRE_WORDS)
    if fire and not _negated(text, fire):
        degree = "total" if _has(text, TOTAL_WORDS) else "partial"
        return state("burnt", degree, "part" if part else "whole")
    demolish = _has(text, DEMOLISH_WORDS)
    if demolish and not _negated(text, demolish):
        if part:
            return None
        return state("demolished")
    if _has(text, MOVE_WORDS):
        if part or _occupant_moved(event, detail):
            return None
        return state("moved")
    if _has(text, REBUILD_WORDS):
        if _has(text, START_WORDS):
            return state("under_construction")
        return state("rebuilt")
    if "construction" in text and "reconstruction" not in text:
        if _has(text, FINAL_WORDS):
            return state("standing")
        return state("under_construction")
    if _has(text, STANDING_WORDS):
        return state("standing")
    if _has(text, RESTORE_WORDS):
        if _has(text, START_WORDS):
            return state("under_construction")
        return state("standing")
    if _has(text, ALTER_WORDS):
        return state("standing")
    damage = _has(text, DAMAGE_WORDS)
    if damage and not _negated(text, damage):
        total = _has(text, TOTAL_WORDS) or re.search(r"\bdied\b|\bdead\b", text)
        return state("damaged", "total" if total else "partial",
                     "part" if part else "whole")
    if visible_change.strip() and not part:
        return state("standing")
    return None


def format_wikidate(time_value: str, precision: int) -> str:
    """Wikidata time plus its precision as a caption phrase.

    9 is a year, 8 a decade, 7 a century, lower is vaguer; day and
    month precision (11, 10) still read as the year.
    """
    match = re.search(r"\+?(-?\d{1,4})-", time_value)
    year = int(match.group(1)) if match else 0
    if precision == 8:
        return f"in the {year // 10 * 10}s"
    if precision == 7:
        century = year // 100 + 1  # Wikidata stores a century as its first year
        suffix = "th" if 11 <= century % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(century % 10, "th")
        return f"in the {century}{suffix} century"
    if precision < 7:
        return f"around {year}"
    return f"in {year}"


# A transient state spanning longer than this is flagged and re-checked,
# never painted silently. Ruins and damage clear when the next segment
# corroborates the span (reconstruction follows the ruin); construction
# and fire clear only when the claim itself states the span.
SPAN_LIMITS = {
    "under_construction": 30,
    "ruin": 50,
    "burnt": 20,
    "damaged": 50,
}
SPAN_SUCCESSORS = {
    "ruin": ("under_construction", "rebuilt", "standing"),
    "damaged": ("standing", "rebuilt", "under_construction"),
}


def _span_stated(claim_text: str, duration: int) -> bool:
    """The claim states a span covering the segment ("for 80 years")."""
    for match in re.finditer(r"([\d,]+)\s*(?:-\s*)?years?\b", claim_text.lower()):
        if int(match.group(1).replace(",", "")) >= duration * 0.7:
            return True
    for match in re.finditer(r"\b(?:for|took|over)\s+([\d,]+)\b", claim_text.lower()):
        if int(match.group(1).replace(",", "")) >= duration * 0.7:
            return True
    return False


def check_span(condition: str, from_year, to_year, claim_text: str = "",
             next_condition: str | None = None) -> str | None:
    """Flag an implausibly long transient state, or None when it reads true."""
    limit = SPAN_LIMITS.get(condition)
    if limit is None or to_year is None:
        return None
    duration = to_year - from_year
    if duration <= limit:
        return None
    if _span_stated(claim_text or "", duration):
        return None
    if next_condition in SPAN_SUCCESSORS.get(condition, ()):
        return None
    return f"{condition} spans {duration} years, longer than the claim supports"


def date_label(date_text: str, year: int) -> str:
    """Display date: the range or vague phrase when one is given, else the year."""
    text = (date_text or "").strip()
    if not text:
        return str(year)
    ranged = re.match(r"between (.+) and (.+)", text)
    if ranged:
        return f"about {ranged.group(1)} to {ranged.group(2)}"
    if text.lower().startswith("in "):
        text = text[3:]
    return text or str(year)
