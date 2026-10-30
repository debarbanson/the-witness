"""Children's captions (step 2/3 for the 8+ audience).

Same verified facts, told simply: every caption is rewritten from its
adult line against the same source sentence, then verified again. A
rewrite that fails is retried plainer once, else dropped. Model calls
are injected, so tests run without live calls.
"""

from witness.verify import keywords_for_claim, select_paragraphs


GENTLE_CONDITIONS = frozenset({"damaged", "burnt", "ruin", "demolished"})


def rewrite_prompt(adult, source, gentle=False) -> str:
    """One idea, everyday words, nothing beyond the source. Heavy
    moments are stated gently but truthfully."""
    prompt = (
        "Rewrite this museum caption for a child aged 8: first person, "
        "short sentences, everyday words, one idea. Say only what the "
        f"source sentence says, no more. Source: {source} "
        f"Adult caption: {adult}")
    if gentle:
        prompt += (" State it gently but truthfully: no frightening "
                   "words, no one in danger.")
    return prompt


def child_caption(rewrite_call, support_call, adult, source, url,
                  gentle=False, year=0, object_name="", texts=None) -> dict:
    """Rewrite plus re-verification; plainer retry once, else drop.
    Every rewrite is checked again against the bound passage, judged
    with its object and year like every other voice text. Fetched
    article text adds the paragraphs research judged, when given."""
    passages = [f"{url}\n{source}"]
    if texts:
        keywords = keywords_for_claim(adult)
        for para in select_paragraphs(texts.get(url) or "", year or None,
                                      keywords, max_paras=3):
            entry = f"{url}\n{para}"
            if entry not in passages:
                passages.append(entry)
        passages = passages[:10]
    for attempt, plain in enumerate((False, True), 1):
        line = (rewrite_call(adult, source, plain, gentle) or "").strip()
        judged = (f"In {year}, {object_name}: {line}"
                  if object_name else line)
        if line and support_call(judged, passages) == "supported":
            return {"line": line, "verified": True, "attempts": attempt}
    return {"line": None, "verified": False, "attempts": 2}


def claim_for_line(claims, year, url):
    """The verified claim a caption line came from: lines are built
    from the first claim in (year, claim) order, so the lookup walks
    the same order."""
    ordered = sorted(claims, key=lambda c: (c.get("year", 0),
                                            c.get("claim", "")))
    for claim in ordered:
        if claim.get("year") == year and claim.get("url") == url:
            return claim
    return None
