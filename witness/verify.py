"""Step 3: verify each claim against its source snippets.

A second model call answers supported | unsupported | partly, quoting the
supporting sentence. Partly claims are rewritten to what the source says.
The same pass applies the content rules: war-only or politics-only claims
are flagged so the film can summarise or skip them.
"""

import json
import re
import time
from urllib.parse import unquote, urlparse

import requests

from witness.web import USER_AGENT, WebError, mediawiki_get

VERDICTS = ("supported", "unsupported", "partly")

WAR_WORDS = frozenset(
    {"war", "bombed", "bombing", "battle", "combat", "soldier", "military", "oorlog", "bezetting", "bombardement", "leger", "militair"}
)
POLITICS_WORDS = frozenset(
    {"election", "council", "mayor", "party", "minister", "parliament", "politic", "verkiezing", "gemeenteraad", "burgemeester", "partij"}
)


class VerifyError(Exception):
    """The verify call failed or returned an unusable verdict."""


def verify_claim(respond, claim, snippets) -> dict:
    """Check one claim. `respond(prompt)` returns a parsed response dict."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))
    prompt = (
        "Claim to check:\n"
        f"{claim}\n\n"
        "Source snippets:\n"
        f"{numbered}\n\n"
        "Answer with a JSON object only: {\"verdict\": \"supported\" | "
        "\"unsupported\" | \"partly\", \"quote\": the sentence that supports "
        "it (empty when unsupported), \"rewritten\": the claim rewritten to "
        "what the sources say (only when partly), \"war_politics_only\": true "
        "when the claim is only about war, armed conflict or politics}."
    )
    response = respond(prompt)
    messages = [o for o in response.get("output", []) if o.get("type") == "message"]
    if not messages:
        raise VerifyError("answer has no messages")
    try:
        parsed = json.loads(messages[-1]["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise VerifyError(f"verdict is not JSON: {exc}")
    if parsed.get("verdict") not in VERDICTS:
        raise VerifyError(f"bad verdict: {parsed.get('verdict')!r}")
    return {
        "verdict": parsed["verdict"],
        "quote": parsed.get("quote", ""),
        "rewritten": parsed.get("rewritten"),
        "war_politics_only": bool(parsed.get("war_politics_only", False)),
    }


def fetch_evidence(urls, get=None, chars=1500, limit=3, sleep=time.sleep) -> list:
    """Source text for the verify call. Wikipedia URLs are read through the
    extracts API; anything else is skipped (a known limitation, logged by
    the caller). One request at a time, cached responses."""
    get = get or requests.get
    evidence = []
    for url in urls:
        if len(evidence) >= limit:
            break
        parsed = urlparse(url)
        if not parsed.netloc.lower().endswith("wikipedia.org"):
            continue
        lang = parsed.netloc.split(".")[0]
        title = unquote(parsed.path.removeprefix("/wiki/"))
        try:
            data = mediawiki_get(
                get,
                f"https://{lang}.wikipedia.org/w/api.php",
                {
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": 1,
                    "exsectionformat": "plain",
                    "titles": title,
                    "format": "json",
                },
                sleep=sleep,
            )
        except WebError as exc:
            raise VerifyError(str(exc))
        for page in data.get("query", {}).get("pages", {}).values():
            extract = (page.get("extract") or "")[:chars]
            if extract:
                evidence.append(f"{url}\n{extract}")
    return evidence


def flag_content(text: str) -> set:
    """Keyword pre-flag for war or politics (English and Dutch)."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    flags = set()
    if words & WAR_WORDS:
        flags.add("war")
    if words & POLITICS_WORDS:
        flags.add("politics")
    return flags
