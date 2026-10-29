"""Step 3: verify each claim against its source snippets.

A second model call answers supported | unsupported | partly, quoting the
supporting sentence. Partly claims are rewritten to what the source says.
The same pass applies the content rules: war-only or politics-only claims
are flagged so the film can summarise or skip them.
"""

import html as html_module
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

import requests

from witness import models
from witness import states
from witness.research import is_weak_source
from witness.web import USER_AGENT, WebError, assert_public_url, mediawiki_get

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
_html_cache: dict = {}


def clear_cache() -> None:
    _cache.clear()
    _html_cache.clear()


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


QUOTE_MARKS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u00ab": '"', "\u00bb": '"',
})


def normalise_text(text: str) -> str:
    """Whitespace runs collapse, curly quotes go straight, ends trimmed."""
    return re.sub(r"\s+", " ", (text or "").translate(QUOTE_MARKS)).strip()


ANCHOR_BUILT_WORDS = frozenset({
    # Construction and opening words; uncovered languages fall back to a vote.
    "built", "erected", "constructed", "completed", "finished", "opened",
    "inaugurated", "unveiled", "founded", "established",
    "gebouwd", "opgericht", "voltooid", "opgeleverd", "geopend", "onthuld",
    "ingewijd", "gesticht",
    "erbaut", "errichtet", "gebaut", "fertiggestellt", "vollendet", "eröffnet",
    "eingeweiht", "enthüllt", "gegründet",
    "construit", "édifié", "bâti", "achevé", "terminé", "inauguré", "ouvert",
    "fondé",
    "construido", "edificado", "terminado", "completado", "inaugurado",
    "abierto", "fundado",
    "construït", "edificat", "acabat", "terminat", "inaugurat", "obert",
    "fundat",
    "costruito", "edificato", "completato", "terminato", "inaugurato",
    "aperto", "fondato",
    "construído", "edificado", "concluído", "terminado", "inaugurado",
    "aberto", "fundado",
    "bygget", "opført", "færdig", "åbnet", "indviet", "grundlagt", "stiftet",
    "byggd", "uppförd", "färdig", "öppnad", "invigd", "grundad",
})

ANCHOR_REJECT_STEMS = (
    "rebuil", "reconstruct", "restor", "renov", "reopen", "repair",
    "re-erect", "herbouw", "wederopbouw", "wiederaufbau", "restaur",
    "reconstru", "ricostru", "genopbyg", "återuppbygg",
)


def _fetched_para(passage: str):
    """Split a fetched "url\\nparagraph" passage; None for snippets."""
    if "\n" not in passage:
        return None
    url, _, para = passage.partition("\n")
    if urlparse(url or "").scheme not in ("http", "https") or " " in url:
        return None
    return url, para


def anchor_hit(passages, year):
    """A sentence pairing the anchor year with a construction word, from
    the best-ranked fetched source. Weak sources and search snippets
    never decide; rebuild and restoration sentences do not confirm an
    inception. Returns (url, sentence) or None."""
    if year is None:
        return None
    ordered = []
    for passage in passages:
        split = _fetched_para(passage)
        if split is None:
            continue
        url, para = split
        rank = _source_rank(url)
        if rank >= 3:
            continue
        ordered.append((rank, url, para))
    ordered.sort(key=lambda item: item[0])
    for _, url, para in ordered:
        for sentence in re.split(r"(?<=[.!?…。！？])\s+", para):
            cleaned = sentence.strip()
            if len(cleaned) < 30 or str(year) not in cleaned:
                continue
            lowered = cleaned.lower()
            if not any(w in lowered for w in ANCHOR_BUILT_WORDS):
                continue
            if any(stem in lowered for stem in ANCHOR_REJECT_STEMS):
                continue
            return url, cleaned
    return None


def is_literal_quote(quote, passages, year, keywords, min_chars=30) -> bool:
    """The quote really appears in the fetched passages and carries the
    claim's year plus a key word: evidence checked in code, not by vote."""
    if year is None or not keywords:
        return False
    norm = normalise_text(quote)
    if len(norm) < min_chars:
        return False
    lowered = norm.lower()
    if str(year) not in lowered:
        return False
    if not any(k.lower() in lowered for k in keywords):
        return False
    joined = "\n".join(normalise_text(p) for p in passages)
    return norm in joined


def quote_carries_year(quote, year, date_text="") -> bool:
    """The winning quote dates the claim: it carries the claim year
    or its date phrase. Yearless support jobs (captions) never pass."""
    if not isinstance(year, int) or isinstance(year, bool) or year == 0:
        return False
    text = quote or ""
    if str(year) in text:
        return True
    phrase = (date_text or "").strip()
    return len(phrase) > 3 and phrase.lower() in text.lower()


def judge_claim(support_respond, job, search_respond=None, completion_respond=None,
              completion=True, dispute_check=None) -> dict:
    """One claim judged end to end: support vote, second judgement when
    the precheck says evidence is present, completion for state-setting
    claims. Every round is kept in the answer. A supporting sentence
    carrying a dispute tag does not support, unless a clean second
    source confirms the claim."""
    passages, urls = job.get("passages") or [], job.get("urls") or []
    votes = max(1, job.get("votes", 1))
    fast_path = None
    stopper = None
    if job.get("anchor") == "build" and passages:
        hit = anchor_hit(passages, job.get("year"))
        if hit is not None:
            url, sentence = hit
            return {
                "verdict": "supported", "quote": sentence, "url": url,
                "support": [{"url": url, "supports": True, "quote": sentence}],
                "note": "wikidata anchor confirmed in article text",
                "completed": True,
                "completion_note": "wikidata anchor needs no completion check",
                "rewritten": None, "war_politics_only": False,
                "rounds": [], "votes": 0, "fast_path": "anchor",
            }
    if passages:
        def quoted_supported(round):
            return (
                round["verdict"] == "supported"
                and is_literal_quote(round.get("quote", ""), passages,
                                     job.get("year"), job.get("keywords") or [])
            )

        one_more = lambda: _support_round(support_respond, job["claim"], passages)
        rounds = _vote_rounds(one_more, votes, stop=quoted_supported)
        stopper = next((found for found in rounds if quoted_supported(found)), None)
        if stopper is not None:
            fast_path = "literal_quote"
        decided_first = [r for r in rounds if r["verdict"] != "error"]
        if (
            decided_first
            and all(r["verdict"] == "unsupported" for r in decided_first)
            and precheck_hit(job.get("year"), job.get("keywords") or [], passages)
        ):
            rounds.append(_second_judgement(support_respond, job, passages))
    elif search_respond is not None:
        one_more = lambda: _search_round(search_respond, job["claim"], urls)
        rounds = _vote_rounds(one_more, votes)
    else:
        return {
            "verdict": "unsupported", "quote": "", "url": None, "support": [],
            "note": "no evidence", "completed": True, "completion_note": None,
            "rewritten": None, "war_politics_only": False, "rounds": [],
            "votes": 0, "fast_path": None,
        }
    decided = [r for r in rounds if r["verdict"] != "error"]
    if not decided and len(rounds) < 3:
        rounds.append(one_more())  # transport errors are not verdicts: one retry
        decided = [r for r in rounds if r["verdict"] != "error"]
    if not decided:
        note = rounds[0].get("note", "verify failed") if rounds else "verify failed"
        return {
            "verdict": "unverified", "quote": "", "url": None, "support": [],
            "note": f"{note}; no verdict after a retry", "completed": True,
            "completion_note": None, "rewritten": None,
            "war_politics_only": False, "rounds": _slim(rounds),
            "votes": len(rounds), "fast_path": None,
        }
    if fast_path == "literal_quote":
        winner = stopper
        verdict = "supported"
    else:
        counts: dict = {}
        for found in decided:
            counts[found["verdict"]] = counts.get(found["verdict"], 0) + 1
        top = max(counts.values())
        winners = [v for v, n in counts.items() if n == top]
        verdict = decided[-1]["verdict"] if len(winners) > 1 else winners[0]
        winner = next(r for r in reversed(decided) if r["verdict"] == verdict)
    if verdict != "unsupported" and dispute_check is not None:
        support = [dict(entry) for entry in winner.get("support", [])]
        for entry in support:
            if entry.get("supports") and dispute_check(
                    entry.get("url"), entry.get("quote", "")):
                entry["supports"] = False
                entry["note"] = "sentence carries a dispute tag"
        if support and all(not entry.get("supports") for entry in support):
            return {
                "verdict": "unsupported", "quote": winner.get("quote", ""),
                "url": winner.get("url"), "support": support,
                "note": "supporting sentence disputed, no clean source",
                "completed": True, "completion_note": None,
                "rewritten": winner.get("rewritten"),
                "war_politics_only": winner.get("war_politics_only", False),
                "rounds": _slim(rounds), "votes": len(rounds),
                "fast_path": fast_path,
            }
        winner = {**winner, "support": support}
    year = job.get("year")
    dated = isinstance(year, int) and not isinstance(year, bool) and year != 0
    if verdict == "supported" and dated and not quote_carries_year(
            winner.get("quote", ""), year, job.get("date_text", "")):
        prior = winner.get("note") or ""
        note = (f"{prior}; winning quote does not carry the year or date"
                if prior else "winning quote does not carry the year or date")
        verdict = "partly"
        winner = {**winner, "verdict": "partly", "note": note}
    completed, completion_note = True, None
    event, detail = job.get("event", ""), job.get("detail", "")
    needs_completion = states.classify(event, detail) is not None or states.looks_incomplete(event, detail)
    if verdict != "unsupported" and needs_completion and completion:
        try:
            completed = check_completion(
                completion_respond or support_respond, job["claim"], winner.get("quote", "")
            )["completed"]
        except Exception as exc:  # noqa: BLE001 - completion qualifies; support decides
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
        "fast_path": fast_path,
    }


def _vote_rounds(one_round, votes: int, stop=None) -> list:
    """The first two rounds run in parallel; a third only when they
    disagree. Submission order is kept, so the winner never depends
    on which round finished first. Both first rounds always run, even
    when one already decides the vote."""
    if votes <= 1:
        return [one_round()]
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="vote") as pool:
        first = models.submit_context(pool, one_round)
        second = models.submit_context(pool, one_round)
        rounds = [first.result(), second.result()]
    if votes <= 2:
        return rounds
    if stop is not None and any(stop(found) for found in rounds):
        return rounds
    if rounds[0]["verdict"] == "error" or rounds[0]["verdict"] != rounds[1]["verdict"]:
        rounds.append(one_round())
    return rounds


def _support_round(respond, claim, passages) -> dict:
    try:
        return verify_claim(respond, claim, passages)
    except Exception as exc:  # noqa: BLE001 - one bad round never kills its siblings
        return {"verdict": "error", "note": f"verify failed: {exc}"}


def _search_round(respond, claim, urls) -> dict:
    try:
        return verify_with_search(respond, claim, urls)
    except Exception as exc:  # noqa: BLE001 - one bad round never kills its siblings
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


def judge_stream(support_respond, jobs, search_respond=None, completion_respond=None,
                 max_workers=6, completion=True, progress=None,
                 dispute_check=None):
    """Judge several claims at once, yielding (index, result) per claim
    as it finishes. A failing job becomes unverified with a note
    instead of killing the run. `progress("verifying", ...)` names the
    claim a worker picks up; `progress("verify", ...)` fires per
    finished claim, in completion order."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run(job, index):
        if progress is not None:
            progress("verifying", {"index": index, "year": job.get("year"),
                                   "total": len(jobs)})
        try:
            return judge_claim(support_respond, job, search_respond, completion_respond,
                               completion=completion,
                               dispute_check=dispute_check)
        except Exception as exc:  # noqa: BLE001 - one failing call never kills the film
            return {
                "verdict": "unverified", "quote": "", "url": None, "support": [],
                "note": f"verify failed: {exc}", "completed": True,
                "completion_note": None, "rewritten": None,
                "war_politics_only": False, "rounds": [], "votes": 0,
                "fast_path": None,
            }

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {models.submit_context(pool, run, job, i): i
                   for i, job in enumerate(jobs)}
        for done, future in enumerate(as_completed(futures), 1):
            index = futures[future]
            result = future.result()
            if progress is not None:
                progress("verify", {"done": done, "total": len(jobs), "index": index,
                                    "year": jobs[index].get("year")})
            yield index, result
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def judge_all(support_respond, jobs, search_respond=None, completion_respond=None,
              max_workers=6, completion=True, progress=None,
              dispute_check=None) -> list:
    """Judge several claims at once; results keep job order."""
    out = [None] * len(jobs)
    for index, result in judge_stream(support_respond, jobs, search_respond,
                                      completion_respond, max_workers,
                                      completion, progress, dispute_check):
        out[index] = result
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
                timeout=15,
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
        assert_public_url(url)
        resp = get(url, headers={"User-Agent": USER_AGENT}, timeout=(5, 10), stream=True)
        resp.raise_for_status()
        final = getattr(resp, "url", url) or url
        if final != url:
            assert_public_url(final)
        content_type = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
        if content_type and "html" not in content_type.lower():
            raise VerifyError(f"not HTML ({content_type.split(';')[0]}), skipped")
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000:
                raise VerifyError("page over 2 MB, skipped")
            chunks.append(chunk)
        html = b"".join(chunks).decode("utf-8", "replace")
        text = extract_main_text(html)
        title = page_title(html)
        if title and cache is not None:
            cache.put(f"{url}#title", title)
    _cache[url] = text
    if cache is not None:
        cache.put(url, text)
    return text


def page_title(html: str) -> str:
    """The page's own <title>, for the end card."""

    class Title(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts, self.inside = [], False

        def handle_starttag(self, tag, attrs):
            if tag == "title":
                self.inside = True

        def handle_endtag(self, tag):
            if tag == "title":
                self.inside = False

        def handle_data(self, data):
            if self.inside:
                self.parts.append(data)

    parser = Title()
    parser.feed(html[:100_000])
    return html_module.unescape(" ".join("".join(parser.parts).split()))


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
        except Exception as exc:  # noqa: BLE001 - one failing fetch never kills the film
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
            except Exception as exc:  # noqa: BLE001 - one failing fetch never kills the film
                return url, None, str(exc)

    if plain:
        pool = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {pool.submit(run, url): url for url in plain}
            for future in as_completed(futures):
                url, text, error = future.result()
                if error is None:
                    texts[url] = text
                else:
                    errors[url] = error
                note(url)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
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


# Rendered inline dispute templates, bracketed so ordinary prose
# ("the disputed border") never matches.
DISPUTE_MARKERS = ("[dubious", "[disputed", "[citation needed",
                   "[failed verification", "[unreliable source",
                   "[clarification needed")


def disputed_sentence(html_text, quote, full_after=50, prefix_after=200) -> bool:
    """A dispute tag on the quoted sentence: a bracketed marker inside
    it or just after it, where the template renders. Spaces are
    ignored, since extraction splits "[dubious]" apart."""
    text = normalise_text(html_text or "").lower()
    needle = normalise_text(quote or "").lower().rstrip().rstrip(".")
    if not needle:
        return False
    at, after = text.find(needle), full_after
    if at < 0 and len(needle) > 60:
        at, after = text.find(needle[:60]), prefix_after
    if at < 0:
        return False
    window = text[at:at + len(needle) + after].replace(" ", "")
    markers = tuple(marker.replace(" ", "") for marker in DISPUTE_MARKERS)
    return any(marker in window for marker in markers)


def fetch_wikipedia_html(url, get=None, sleep=time.sleep, cache=None) -> str:
    """Parsed article HTML as text, dispute templates intact. Cached
    apart from the plain extracts."""
    key = f"{url} #html"
    if key in _html_cache:
        return _html_cache[key]
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            _html_cache[key] = hit
            return hit
    get = get or requests.get
    parsed = urlparse(url)
    lang = parsed.netloc.split(".")[0]
    title = unquote(parsed.path.removeprefix("/wiki/"))
    data = mediawiki_get(
        get, f"https://{lang}.wikipedia.org/w/api.php",
        {"action": "parse", "page": title, "prop": "text",
         "redirects": 1, "format": "json"},
        sleep=sleep, timeout=15, tries=2)
    try:
        html = data["parse"]["text"]["*"]
    except (KeyError, TypeError) as exc:
        raise VerifyError(f"{url}: no parsed text") from exc
    text = extract_main_text(html)
    _html_cache[key] = text
    if cache is not None:
        cache.put(key, text)
    return text


def sentence_disputed(url, quote, get=None, cache=None) -> bool:
    """Whether the quoted sentence carries a dispute tag in its source.
    Anything unreadable counts as clean: the rule fires only on a tag
    actually seen."""
    if not url or not quote or len(quote) < 30:
        return False
    try:
        if urlparse(url).netloc.lower().endswith("wikipedia.org"):
            text = fetch_wikipedia_html(url, get=get, cache=cache)
        else:
            text = fetch_source_text(url, get=get, cache=cache)
    except Exception:  # noqa: BLE001 - unreadable means no tag seen
        return False
    return disputed_sentence(text, quote)


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
    becomes unverified with a note instead of killing the run)."""
    from concurrent.futures import ThreadPoolExecutor

    def run(job):
        claim, evidence = job
        try:
            return verify_claim(respond, claim, evidence)
        except Exception as exc:  # noqa: BLE001 - one failing call never kills the film
            return {
                "verdict": "unverified", "quote": "", "url": None, "support": [],
                "note": f"verify failed: {exc}", "completed": True,
                "rewritten": None, "war_politics_only": False,
            }

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [models.submit_context(pool, run, job) for job in jobs]
        return [future.result() for future in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def flag_content(text: str) -> set:
    """Keyword pre-flag for war or politics (English and Dutch)."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    flags = set()
    if words & WAR_WORDS:
        flags.add("war")
    if words & POLITICS_WORDS:
        flags.add("politics")
    return flags
