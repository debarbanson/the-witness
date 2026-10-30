"""Children's captions (step 2/3 for the 8+ audience).

Same verified facts, told simply: every caption is rewritten from its
adult line against the same source sentence, then verified again. A
rewrite that fails is retried plainer once, else dropped. Model calls
are injected, so tests run without live calls.
"""


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
                  gentle=False) -> dict:
    """Rewrite plus re-verification; plainer retry once, else drop.
    Every rewrite is checked again against the bound passage."""
    passages = [f"{url}\n{source}"]
    for attempt, plain in enumerate((False, True), 1):
        line = (rewrite_call(adult, source, plain, gentle) or "").strip()
        if line and support_call(line, passages) == "supported":
            return {"line": line, "verified": True, "attempts": attempt}
    return {"line": None, "verified": False, "attempts": 2}


def claim_for_line(claims, year, url):
    """The verified claim a caption line came from, first match."""
    for claim in claims:
        if claim.get("year") == year and claim.get("url") == url:
            return claim
    return None
