"""Adult line-2 sentences (step 7 captions).

One written first-person sentence per scene, made from that scene's own
verified claim and re-verified against its quote. Each claim is used at
most once per film; a scene with no claim of its own gets no sentence
and is dropped from the film. Shortening happens by rewriting, never
by cutting: no ellipsis anywhere. Model calls are injected, so tests
run without live calls.
"""

import re

from witness import states
from witness.verify import filmed, keywords_for_claim, select_paragraphs

TARGET_CHARS = 80  # what the writer aims at; fits two caption lines
MAX_CHARS = 110  # hard gate; beyond this the run fails, nothing is cut

_FIRST_PERSON = re.compile(r"\bI\b|\b[Mm]y\b|\b[Mm]e\b")
_WRONG_VOICE = re.compile(r"\bI saw\b|\b[Ww]e\b|\b[Oo]ur\b|\b[Uu]s\b")
_YEAR = re.compile(r"\b(\d{4})\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_DAY_MONTH = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r")\b",
                        re.IGNORECASE)


def claim_matches(claim, year) -> bool:
    """A claim belongs to a scene when it may be filmed and its year
    is the scene's year or its span covers that year."""
    if not filmed(claim):
        return False
    if isinstance(claim.get("year"), int) and claim["year"] == year:
        return True
    span = (claim.get("from_year"), claim.get("to_year"))
    return (isinstance(span[0], int) and isinstance(span[1], int)
            and span[0] <= year <= span[1])


def claim_detail(claim) -> str:
    """The claim's own words: the narrowed rewrite only for partly
    verdicts, where the rewrite is what the source states. A rewrite
    kept on any other verdict is unchecked model text and never
    reaches paint or captions."""
    if claim.get("verdict") == "partly" and claim.get("rewritten"):
        return claim["rewritten"]
    return claim.get("claim", "")


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


def sentence_prompt(detail, quote, year, stamp=None) -> str:
    """One first-person sentence from the source, no years, no cutting."""
    return (
        "You are the object itself (the mill, the tree, the lighthouse). "
        "Write one first-person sentence for a museum film caption about "
        f"the year {year}: I, my or me, never I saw, we or our. "
        "For the object's parts or buildings, say my (my sails, my buildings). "
        "Cover the claim's main event only, in one short sentence; "
        "leave out secondary detail. Include an age only when the source "
        "states it in years. "
        "Fold numbers into the sentence naturally; never list them; use "
        "only numbers the source states, never compute one yourself. "
        "Say only what the source sentences say, no more. "
        "Say only what the sources agree on: if they disagree on a detail, "
        "leave that detail out. "
        "Do not mention any year or date; the film already shows "
        f"{'the date ' + stamp if stamp else 'the year'}. "
        f"At most {TARGET_CHARS} characters, never cut off mid-word. "
        f"Source: {quote} Claim: {detail}")


def other_texts(assigned, claims, year) -> list:
    """Evidence the writer must respect beyond the main quote: the
    scene's other verified claims (their words plus their supporting
    quotes) and the assigned claim's other supporting quotes."""
    texts = []
    main = (assigned.get("quote") or "")

    def supporting(claim):
        return [e.get("quote", "") for e in (claim.get("support") or [])
                if e.get("supports") and e.get("quote")]

    for claim in claims:
        if claim is assigned or not claim_matches(claim, year):
            continue
        detail = claim_detail(claim)
        if detail:
            texts.append(detail)
        if claim.get("quote"):
            texts.append(claim["quote"])
        texts.extend(supporting(claim))
    texts.extend(q for q in supporting(assigned) if q != main)
    return list(dict.fromkeys(texts))


def sentence_ok(sentence) -> bool:
    """Code gate: first person, never a date, fits, never cut.

    The gold stamp already shows the date, so the sentence leaves it
    out: no 4-digit years, no day and month. Durations ("70 years",
    "800 years old") are not dates and stay allowed.
    """
    if not sentence or "…" in sentence or len(sentence) > MAX_CHARS:
        return False
    if not _FIRST_PERSON.search(sentence):
        return False
    if _WRONG_VOICE.search(sentence):
        return False
    if _YEAR.search(sentence):
        return False
    if _DAY_MONTH.search(sentence):
        return False
    return True


def numbers_supported(sentence, quote) -> bool:
    """Every number in the sentence (years, ages, counts, distances)
    appears in the evidence quote. A partial digit run never counts:
    70 is not in 700."""
    text = (quote or "").replace(",", "")
    for raw in _NUMBER.findall(sentence or ""):
        number = raw.replace(",", "")
        if not re.search(rf"(?<!\d){re.escape(number)}(?!\d)", text):
            return False
    return True


def evidence_passages(assigned, claims, year) -> list:
    """Bound evidence for the sentence check: the assigned claim's
    accepted quote plus the other accepted quotes of the scene's
    year, each with the URL it was fetched from."""
    passages = []
    main = assigned.get("quote", "")
    if assigned.get("url") and main:
        passages.append(f"{assigned['url']}\n{main}")
    for claim in claims:
        if claim is assigned or not claim_matches(claim, year):
            continue
        url, quote = claim.get("url"), claim.get("quote", "")
        if url and quote and quote != main:
            passages.append(f"{url}\n{quote}")
    return passages


def check_passages(claim, claims, year, texts, max_paras=3) -> list:
    """Bound quotes plus the paragraphs that mention the claim's year
    or key words, as research judged them: one sentence rarely holds
    the object, the date and the event together."""
    bound = evidence_passages(claim, claims, year)
    if not texts:
        return bound
    keywords = keywords_for_claim(claim.get("claim", ""),
                                  claim.get("event", ""))
    urls = []
    for passage in bound:
        url = passage.split("\n", 1)[0]
        if url not in urls:
            urls.append(url)
    rich = list(bound)
    for url in urls:
        for para in select_paragraphs(texts.get(url) or "", year, keywords,
                                      max_paras=max_paras):
            entry = f"{url}\n{para}"
            if entry not in rich:
                rich.append(entry)
    return rich[:10]


def write_sentence(rewrite_call, support_call, claim, year,
                   claims=(), stamp="", object_name="", texts=None) -> dict:
    """Rewrite plus re-verification; shorter retry once, else failure.

    The writer sees the scene's other kept evidence with the main
    quote, and every rewrite is checked again against the bound
    passages: the accepted quotes with their URLs. The check is bound
    to the claim's year and key words, and every number in the
    sentence must appear in the accepted quote. Only a fully
    supported sentence counts. The judge sees the sentence with its
    object and year, exactly what the film asserts with its stamp.
    The returned evidence is the sentence that supported the caption.
    """
    detail = claim_detail(claim)
    main = claim.get("quote", "")
    others = [text for text in other_texts(claim, claims, year)
              if text and text != main]
    source = main if not others else (
        f"{main}\n\nOther kept evidence:\n" + "\n".join(others))
    if texts is None:
        passages = evidence_passages(claim, claims, year)
    else:
        passages = check_passages(claim, claims, year, texts)
    keywords = keywords_for_claim(claim.get("claim", ""),
                                  claim.get("event", ""))
    for attempt, plain in enumerate((False, True), 1):
        sentence = ""
        for _ in range(3):  # empty answers are retried, never judged
            sentence = (rewrite_call(detail, source, year, plain, stamp)
                        or "").strip()
            if sentence:
                break
        judged = (f"In {year}, {object_name}: {sentence}"
                  if object_name else sentence)
        if not (sentence and sentence_ok(sentence)
                and numbers_supported(sentence, main)):
            continue
        result = support_call(judged, passages, year, keywords)
        if isinstance(result, dict):
            verdict = result.get("verdict")
            evidence = {"quote": result.get("quote", ""),
                        "url": result.get("url", "")}
        else:
            verdict, evidence = result, {"quote": main,
                                         "url": claim.get("url", "")}
        if verdict == "supported":
            return {"sentence": sentence, "verified": True,
                    "attempts": attempt, "evidence": evidence}
    return {"sentence": None, "verified": False, "attempts": 2,
            "evidence": {"quote": "", "url": ""}}
