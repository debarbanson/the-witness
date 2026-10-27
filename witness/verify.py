"""Step 3: verify each claim against its source snippets.

A second model call answers supported | unsupported | partly, quoting the
supporting sentence. Partly claims are rewritten to what the source says.
The same pass applies the content rules: war-only or politics-only claims
are flagged so the film can summarise or skip them.
"""

import json
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

import requests

from witness import states
from witness.research import is_weak_source
from witness.web import USER_AGENT, WebError, mediawiki_get

VERDICTS = ("supported", "unsupported", "partly")

# Quote preference among supporting sources: encyclopedias first, then
# heritage and public bodies, then the rest, weak sites never.
GOOD_HOST_HINTS = ("heritage", "museum", "archive", "register")

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


def text_answer(text: str) -> dict:
    """Plain answer text wrapped as a response, so Chat Completions
    answers parse through the same contract."""
    return {"output": [{"type": "message",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}


def verify_claim(respond, claim, snippets) -> dict:
    """Support check: does a passage state this fact? Passages only, no
    web search and no completion question; those are separate calls."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))
    prompt = (
        "Claim to check:\n"
        f"{claim}\n\n"
        "Source passages (each starts with its page URL). Judge the claim "
        "against these passages only:\n"
        f"{numbered}\n\n"
        "For every passage say whether its text states the claim, with the "
        "sentence that states it. "
        "Answer with a JSON object only: {\"verdict\": \"supported\" | "
        "\"unsupported\" | \"partly\", \"quote\": the sentence that states "
        "it (empty when unsupported), \"url\": the page the quote comes from, "
        "\"support\": [{\"url\", \"supports\": true|false, \"quote\"}] for "
        "each passage, \"rewritten\": the claim rewritten to what the "
        "passages state (only when partly), \"war_politics_only\": true "
        "when the claim is only about war, armed conflict or politics}."
    )
    return _judge_support(respond(prompt))


def verify_with_search(respond, claim, urls) -> dict:
    """Support fallback when no passage was fetched: check the claim with
    web search against its cited sources. Same answer contract."""
    listed = "\n".join(f"- {u}" for u in urls)
    prompt = (
        "Claim to check:\n"
        f"{claim}\n\n"
        f"Cited sources:\n{listed}\n\n"
        "No passage text is available, so use web search to check the claim "
        "against its cited sources or other pages. For every page you used, "
        "say whether its text states the claim, with the sentence that "
        "states it. "
        "Answer with a JSON object only: {\"verdict\": \"supported\" | "
        "\"unsupported\" | \"partly\", \"quote\": the sentence that states "
        "it (empty when unsupported), \"url\": the page the quote comes from, "
        "\"support\": [{\"url\", \"supports\": true|false, \"quote\"}] for "
        "each page used, \"rewritten\": the claim rewritten to what the "
        "sources state (only when partly), \"war_politics_only\": true "
        "when the claim is only about war, armed conflict or politics}."
    )
    return _judge_support(respond(prompt))


def check_completion(respond, claim, evidence="") -> dict:
    """Completion check, asked separately and narrowly: did this change
    actually happen, or was it only planned, promised, proposed or
    attempted? Only for claims that would set a state."""
    prompt = (
        "Claim:\n"
        f"{claim}\n\n"
        f"Supporting evidence:\n{evidence}\n\n"
        "Did this change actually happen, or was it only planned, promised, "
        "proposed or attempted? A change that never happened is not an "
        "event, even when the claim states it as one. "
        "Answer with a JSON object only: {\"completed\": true|false}."
    )
    response = respond(prompt)
    messages = [o for o in response.get("output", []) if o.get("type") == "message"]
    if not messages:
        raise VerifyError("answer has no messages")
    try:
        parsed = json.loads(messages[-1]["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise VerifyError(f"completion is not JSON: {exc}")
    if not isinstance(parsed.get("completed"), bool):
        raise VerifyError(f"bad completed flag: {parsed.get('completed')!r}")
    return {"completed": parsed["completed"]}


def _judge_support(response) -> dict:
    """One support answer parsed: verdict, quality override, best quote."""
    messages = [o for o in response.get("output", []) if o.get("type") == "message"]
    if not messages:
        raise VerifyError("answer has no messages")
    try:
        parsed = json.loads(messages[-1]["content"][0]["text"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise VerifyError(f"verdict is not JSON: {exc}")
    if parsed.get("verdict") not in VERDICTS:
        raise VerifyError(f"bad verdict: {parsed.get('verdict')!r}")
    support = parsed.get("support")
    if support is None:  # answers from before per-source support
        support = [
            {
                "url": parsed.get("url", ""),
                "supports": parsed["verdict"] in ("supported", "partly"),
                "quote": parsed.get("quote", ""),
            }
        ]
    supporting = [s for s in support if s.get("supports")]
    good = [s for s in supporting if not is_weak_source(s.get("url", ""))]
    verdict, note = parsed["verdict"], None
    if not supporting:
        verdict, note = "unsupported", "no supporting source"
    elif not good:
        verdict, note = "unsupported", "weak sources only"
    quote, url = parsed.get("quote", ""), parsed.get("url")
    if good:
        best = min(good, key=lambda s: _source_rank(s.get("url", "")))
        if _source_rank(best.get("url", "")) < _source_rank(url or "") or not quote:
            quote, url = best.get("quote", ""), best.get("url")
    return {
        "verdict": verdict,
        "quote": quote,
        "url": url,
        "support": support,
        "note": note,
        "rewritten": parsed.get("rewritten"),
        "war_politics_only": bool(parsed.get("war_politics_only", False)),
    }


def _source_rank(url: str) -> int:
    """Lower is a better source to quote."""
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if is_weak_source(url or ""):
        return 3
    if host.endswith(("wikipedia.org", "wikidata.org", "wikimedia.org")):
        return 0
    parts = host.split(".")
    if "gov" in parts or "edu" in parts:
        return 1
    if any(hint in host for hint in GOOD_HOST_HINTS):
        return 1
    return 2


def precheck_hit(year, keywords, passages) -> bool:
    """Deterministic evidence signal: one passage holds the claim's year
    and at least one of its key words."""
    if year is None:
        return False
    for passage in passages:
        lowered = passage.lower()
        if str(year) in lowered and any(k.lower() in lowered for k in keywords):
            return True
    return False


def judge_claim(support_respond, job, search_respond=None, completion_respond=None,
              completion=True) -> dict:
    """One claim judged end to end: support vote, second judgement when
    the precheck says evidence is present, completion for state-setting
    claims. Every round is kept in the answer."""
    passages, urls = job.get("passages") or [], job.get("urls") or []
    votes = max(1, job.get("votes", 1))
    if passages:
        rounds = _vote_rounds(
            lambda: _support_round(support_respond, job["claim"], passages), votes)
        decided_first = [r for r in rounds if r["verdict"] != "error"]
        if (
            decided_first
            and all(r["verdict"] == "unsupported" for r in decided_first)
            and precheck_hit(job.get("year"), job.get("keywords") or [], passages)
        ):
            rounds.append(_second_judgement(support_respond, job, passages))
    elif search_respond is not None:
        rounds = _vote_rounds(
            lambda: _search_round(search_respond, job["claim"], urls), votes)
    else:
        return {
            "verdict": "unsupported", "quote": "", "url": None, "support": [],
            "note": "no evidence", "completed": True, "completion_note": None,
            "rewritten": None, "war_politics_only": False, "rounds": [], "votes": 0,
        }
    decided = [r for r in rounds if r["verdict"] != "error"]
    if not decided:
        note = rounds[0].get("note", "verify failed") if rounds else "verify failed"
        return {
            "verdict": "unsupported", "quote": "", "url": None, "support": [],
            "note": note, "completed": True, "completion_note": None,
            "rewritten": None, "war_politics_only": False,
            "rounds": _slim(rounds), "votes": len(rounds),
        }
    counts: dict = {}
    for found in decided:
        counts[found["verdict"]] = counts.get(found["verdict"], 0) + 1
    top = max(counts.values())
    winners = [v for v, n in counts.items() if n == top]
    verdict = decided[-1]["verdict"] if len(winners) > 1 else winners[0]
    winner = next(r for r in reversed(decided) if r["verdict"] == verdict)
    completed, completion_note = True, None
    event, detail = job.get("event", ""), job.get("detail", "")
    needs_completion = states.classify(event, detail) is not None or states.looks_incomplete(event, detail)
    if verdict != "unsupported" and needs_completion and completion:
        try:
            completed = check_completion(
                completion_respond or support_respond, job["claim"], winner.get("quote", "")
            )["completed"]
        except VerifyError as exc:
            completion_note = f"completion check failed: {exc}"
    return {
        "verdict": winner["verdict"],
        "quote": winner.get("quote", ""),
        "url": winner.get("url"),
        "support": winner.get("support", []),
        "note": winner.get("note"),
        "completed": completed,
        "completion_note": completion_note,
        "rewritten": winner.get("rewritten"),
        "war_politics_only": winner.get("war_politics_only", False),
        "rounds": _slim(rounds),
        "votes": len(rounds),
    }


def _vote_rounds(one_round, votes: int) -> list:
    """Vote rounds with early stop: when the first two decided answers
    agree, the third call is skipped."""
    rounds = []
    while len(rounds) < votes:
        rounds.append(one_round())
        if len(rounds) == 2:
            first, second = rounds
            if (first["verdict"] != "error" and first["verdict"] == second["verdict"]):
                break
    return rounds


def _support_round(respond, claim, passages) -> dict:
    try:
        return verify_claim(respond, claim, passages)
    except VerifyError as exc:
        return {"verdict": "error", "note": f"verify failed: {exc}"}


def _search_round(respond, claim, urls) -> dict:
    try:
        return verify_with_search(respond, claim, urls)
    except VerifyError as exc:
        return {"verdict": "error", "note": f"verify failed: {exc}"}


def _second_judgement(respond, job, passages) -> dict:
    """The precheck found the year and key words in a passage, so an
    unsupported verdict is not accepted outright: one confrontation
    round that must quote what decides it either way."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(passages))
    prompt = (
        "Claim to check:\n"
        f"{job['claim']}\n\n"
        "Source passages (each starts with its page URL):\n"
        f"{numbered}\n\n"
        f"Another judge marked this claim unsupported, but a passage contains "
        f"the year {job.get('year')} and words from the claim. Reconsider: "
        "quote the sentence that decides it either way and give your final "
        "verdict. "
        "Answer with a JSON object only: {\"verdict\": \"supported\" | "
        "\"unsupported\" | \"partly\", \"quote\": the deciding sentence "
        "(empty when unsupported), \"url\": the page the quote comes from, "
        "\"support\": [{\"url\", \"supports\": true|false, \"quote\"}] for "
        "each passage, \"rewritten\": the claim rewritten to what the "
        "passages state (only when partly), \"war_politics_only\": true "
        "when the claim is only about war, armed conflict or politics}."
    )
    try:
        return _judge_support(respond(prompt))
    except VerifyError as exc:
        return {"verdict": "error", "note": f"verify failed: {exc}"}


def _slim(rounds) -> list:
    return [{"verdict": r.get("verdict"), "quote": r.get("quote", ""),
             "url": r.get("url")} for r in rounds]


def judge_all(support_respond, jobs, search_respond=None, completion_respond=None,
              max_workers=6, completion=True, progress=None) -> list:
    """Judge several claims at once (a failing job becomes unsupported
    with a note instead of killing the run). `progress("verify", ...)`
    fires per finished claim, in completion order; results keep job order."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run(job):
        try:
            return judge_claim(support_respond, job, search_respond, completion_respond,
                               completion=completion)
        except VerifyError as exc:
            return {
                "verdict": "unsupported", "quote": "", "url": None, "support": [],
                "note": f"verify failed: {exc}", "completed": True,
                "completion_note": None, "rewritten": None,
                "war_politics_only": False, "rounds": [], "votes": 0,
            }

    out = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run, job): i for i, job in enumerate(jobs)}
        for done, future in enumerate(as_completed(futures), 1):
            out[futures[future]] = future.result()
            if progress is not None:
                progress("verify", {"done": done, "total": len(jobs)})
    return out


def fetch_source_text(url, get=None, sleep=time.sleep, cache=None) -> str:
    """Full text of one cited source, cached. Wikipedia URLs go through the
    extracts API in the article's own language; other pages are fetched with
    a plain GET and reduced to their main paragraphs."""
    if url in _cache:
        return _cache[url]
    if cache is not None:
        hit = cache.get(url)
        if hit is not None:
            _cache[url] = hit
            return hit
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
                timeout=30,
                tries=2,
            )
        except WebError as exc:
            raise VerifyError(str(exc))
        text = strip_reference_tail(
            "\n\n".join(
                page.get("extract", "")
                for page in data.get("query", {}).get("pages", {}).values()
            )
        )
    else:
        resp = get(url, headers={"User-Agent": USER_AGENT}, timeout=(5, 10), stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
        if content_type and "html" not in content_type.lower():
            raise VerifyError(f"not HTML ({content_type.split(';')[0]}), skipped")
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000:
                raise VerifyError("page over 2 MB, skipped")
            chunks.append(chunk)
        text = extract_main_text(b"".join(chunks).decode("utf-8", "replace"))
    _cache[url] = text
    if cache is not None:
        cache.put(url, text)
    return text


REFERENCE_SECTIONS = frozenset({
    # Trailing sections that list sources, never evidence (en, de, fr, nl).
    "references", "einzelnachweise", "referenzen", "références", "referenties",
    "notes", "noten", "fußnoten", "notizen", "anmerkungen",
    "see also", "siehe auch", "voir aussi", "zie ook",
    "external links", "weblinks", "web links", "liens externes", "externe links",
    "further reading", "literatur", "bibliographie", "bibliografie", "bronnen",
    "sources", "quellen",
})


def strip_reference_tail(text: str) -> str:
    """Cut a Wikipedia extract at its trailing reference sections.

    Citations carry years and names but prove nothing; keeping them
    bloats prompts and fakes year matches in paragraph selection.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip("= ").lower() in REFERENCE_SECTIONS:
            return "\n".join(lines[:i]).rstrip("\n")
    return text


def fetch_many(urls, get=None, sleep=time.sleep, cache=None, max_workers=8, progress=None):
    """Fetch many source pages: Wikimedia URLs one at a time in this
    thread (their rule), plain pages in parallel with at most one
    request per host at a time. Returns (texts, errors); a failure is
    logged by the caller and skipped, never retried."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    get = get or requests.get
    texts: dict = {}
    errors: dict = {}

    def note(url):
        if progress is not None:
            progress("fetch", {"done": len(texts) + len(errors),
                               "total": len(urls), "url": url})

    wiki = [u for u in urls if urlparse(u).netloc.lower().endswith(
        ("wikipedia.org", "wikidata.org", "wikimedia.org"))]
    for url in wiki:
        try:
            texts[url] = fetch_source_text(url, get=get, sleep=sleep, cache=cache)
        except (VerifyError, WebError, OSError) as exc:
            errors[url] = str(exc)
        note(url)
    plain = [u for u in urls if u not in texts and u not in errors]
    locks: dict = {}
    locks_guard = threading.Lock()

    def host_lock(url):
        host = urlparse(url).netloc.lower()
        with locks_guard:
            return locks.setdefault(host, threading.Lock())

    def run(url):
        with host_lock(url):
            try:
                return url, fetch_source_text(url, get=get, sleep=sleep, cache=cache), None
            except (VerifyError, WebError, OSError) as exc:
                return url, None, str(exc)

    if plain:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run, url): url for url in plain}
            for future in as_completed(futures):
                url, text, error = future.result()
                if error is None:
                    texts[url] = text
                else:
                    errors[url] = error
                note(url)
    return texts, errors


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


def verify_all(respond, jobs, max_workers=6) -> list:
    """Verify several claims at once (Meta calls parallelise; a failing job
    becomes unsupported with a note instead of killing the run)."""
    from concurrent.futures import ThreadPoolExecutor

    def run(job):
        claim, evidence = job
        try:
            return verify_claim(respond, claim, evidence)
        except VerifyError as exc:
            return {
                "verdict": "unsupported", "quote": "", "url": None, "support": [],
                "note": f"verify failed: {exc}", "completed": True,
                "rewritten": None, "war_politics_only": False,
            }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(run, jobs))


def flag_content(text: str) -> set:
    """Keyword pre-flag for war or politics (English and Dutch)."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    flags = set()
    if words & WAR_WORDS:
        flags.add("war")
    if words & POLITICS_WORDS:
        flags.add("politics")
    return flags
