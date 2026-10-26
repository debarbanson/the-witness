"""Step 3: verify each claim against its source snippets.

A second model call answers supported | unsupported | partly, quoting the
supporting sentence. Partly claims are rewritten to what the source says.
The same pass applies the content rules: war-only or politics-only claims
are flagged so the film can summarise or skip them.
"""

import json
import re
import time
from html.parser import HTMLParser
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
STOPWORDS = frozenset(
    """the a an and or of to in on for with by from as at is was were are be been
    het een en van tot in op voor met door als is was waren zijn wordt werden
    this that these those it its into over after before than then there their""".split()
)

_cache: dict = {}


def clear_cache() -> None:
    _cache.clear()


class VerifyError(Exception):
    """The verify call failed or returned an unusable verdict."""


def verify_claim(respond, claim, snippets) -> dict:
    """Check one claim. `respond(prompt)` returns a parsed response dict."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))
    prompt = (
        "Claim to check:\n"
        f"{claim}\n\n"
        "Source passages:\n"
        f"{numbered}\n\n"
        "Judge the claim against these passages. When they do not settle it, "
        "use web search to check the claim against its cited sources or other "
        "pages, and say which page each quoted sentence comes from. "
        "Answer with a JSON object only: {\"verdict\": \"supported\" | "
        "\"unsupported\" | \"partly\", \"quote\": the sentence that supports "
        "it (empty when unsupported), \"url\": the page the quote comes from, "
        "\"rewritten\": the claim rewritten to what the sources say (only "
        "when partly), \"war_politics_only\": true when the claim is only "
        "about war, armed conflict or politics}."
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
        "url": parsed.get("url"),
        "rewritten": parsed.get("rewritten"),
        "war_politics_only": bool(parsed.get("war_politics_only", False)),
    }


def fetch_source_text(url, get=None, sleep=time.sleep) -> str:
    """Full text of one cited source, cached. Wikipedia URLs go through the
    extracts API in the article's own language; other pages are fetched with
    a plain GET and reduced to their main paragraphs."""
    if url in _cache:
        return _cache[url]
    get = get or requests.get
    parsed = urlparse(url)
    if parsed.netloc.lower().endswith("wikipedia.org"):
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
        text = "\n\n".join(
            page.get("extract", "")
            for page in data.get("query", {}).get("pages", {}).values()
        )
    else:
        resp = get(url, headers={"User-Agent": USER_AGENT}, timeout=90)
        resp.raise_for_status()
        text = extract_main_text(resp.text)
    _cache[url] = text
    return text


def extract_main_text(html: str, min_words=6) -> str:
    """Paragraph text of a page: script, style and chrome dropped."""

    class Paragraphs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.paras, self.current, self.skip = [], [], 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip += 1
            if tag == "p":
                self.current = []

        def handle_endtag(self, tag):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip = max(self.skip - 1, 0)
            if tag == "p" and self.current:
                self.paras.append(" ".join(self.current))
                self.current = []

        def handle_data(self, data):
            if not self.skip:
                self.current.append(data.strip())

    parser = Paragraphs()
    parser.feed(html)
    kept = [" ".join(p.split()) for p in parser.paras]
    return "\n\n".join(p for p in kept if len(p.split()) >= min_words)


def keywords_for_claim(text: str, event: str = "", limit=8) -> list:
    """Distinctive words of a claim: long words, no stopwords, no years."""
    words = [w for w in re.findall(r"[a-z]+", f"{event} {text}".lower()) if len(w) >= 4]
    return [w for w in dict.fromkeys(words) if w not in STOPWORDS][:limit]


def select_paragraphs(text: str, year=None, keywords=(), max_paras=6) -> list:
    """Paragraphs mentioning the claim's year first, then its key words."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if len(p.split()) >= 6]
    year_hit = [p for p in paras if year is not None and str(year) in p]
    word_hit = [p for p in paras if p not in year_hit and any(k in p.lower() for k in keywords)]
    chosen = year_hit + word_hit
    return (chosen or paras)[:max_paras]


def flag_content(text: str) -> set:
    """Keyword pre-flag for war or politics (English and Dutch)."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    flags = set()
    if words & WAR_WORDS:
        flags.add("war")
    if words & POLITICS_WORDS:
        flags.add("politics")
    return flags
