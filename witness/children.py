"""Children's captions (step 2/3 for the 8+ audience).

Same verified facts, told simply: every caption is rewritten from its
adult line against the same source sentence, then verified again. A
rewrite that fails is retried plainer once, else dropped. Model calls
are injected, so tests run without live calls.
"""

from witness.captions import numbers_supported, sentence_ok
from witness.verify import keywords_for_claim, select_paragraphs


GENTLE_CONDITIONS = frozenset({"damaged", "burnt", "ruin", "demolished"})


def rewrite_prompt(adult, source, gentle=False, stamp="") -> str:
    """One idea, everyday words, nothing beyond the source. Heavy
    moments are stated gently but truthfully. A stamped sentence
    leaves the date to the stamp, like the adult one."""
    prompt = (
        "Rewrite this museum caption for a child aged 8: first person, "
        "short sentences, everyday words, one idea. Say only what the "
        f"source sentence says, no more. Source: {source} "
        f"Adult caption: {adult}")
    if gentle:
        prompt += (" State it gently but truthfully: no frightening "
                   "words, no one in danger.")
    if stamp:
        prompt += (f" Do not mention any year or date; the film already "
                   f"shows the date {stamp}.")
    return prompt


def child_caption(rewrite_call, support_call, adult, source, url,
                  gentle=False, year=0, object_name="", texts=None,
                  stamp="") -> dict:
    """Rewrite plus re-verification; plainer retry once, else drop.
    Every rewrite is checked again against the bound passage, judged
    with its object and year like every other voice text. The check
    is bound to the claim's year and key words, and every number in
    the line must appear in the source sentence. Fetched article text
    adds the paragraphs research judged, when given. A stamped scene
    sentence keeps the adult shape: first person, no year or date;
    unstamped lines keep their years. The returned evidence is the
    sentence that supported the line."""
    passages = [f"{url}\n{source}"]
    keywords = keywords_for_claim(adult)
    if texts:
        for para in select_paragraphs(texts.get(url) or "", year or None,
                                      keywords, max_paras=3):
            entry = f"{url}\n{para}"
            if entry not in passages:
                passages.append(entry)
        passages = passages[:10]
    for attempt, plain in enumerate((False, True), 1):
        line = ""
        for _ in range(3):  # empty answers are retried, never judged
            line = (rewrite_call(adult, source, plain, gentle, stamp)
                    or "").strip()
            if line:
                break
        judged = (f"In {year}, {object_name}: {line}"
                  if object_name else line)
        if not (line and (not stamp or sentence_ok(line))
                and numbers_supported(line, source)):
            continue
        result = support_call(judged, passages, year, keywords)
        if isinstance(result, dict):
            verdict = result.get("verdict")
            evidence = {"quote": result.get("quote", ""),
                        "url": result.get("url", "")}
        else:
            verdict, evidence = result, {"quote": source, "url": url}
        if verdict == "supported":
            return {"line": line, "verified": True, "attempts": attempt,
                    "evidence": evidence}
    return {"line": None, "verified": False, "attempts": 2,
            "evidence": {"quote": "", "url": ""}}


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
