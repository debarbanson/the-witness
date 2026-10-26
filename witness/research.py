"""Step 2: research the object's history, receipts attached.

Wikidata structured facts first (free), then one grounded web question per
call with structured output. Only the last message of an answer is read;
earlier messages narrate the tool use. The source-quality rule drops claims
whose only sources are user-written sites.
"""

import re
import time
from urllib.parse import urlparse

import requests

from witness.web import USER_AGENT, WebError, mediawiki_get

FACT_PROPS = {
    "P571": "inception",
    "P84": "architect",
    "P793": "significant event",
    "P576": "demolished or destroyed",
    "P1435": "heritage designation",
    "P18": "image",
    "P373": "Commons category",
}

LIFESPAN_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "event": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["year", "event", "detail"],
                "additionalProperties": False,
            },
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["events", "sources"],
    "additionalProperties": False,
}

# Event word to the object's state from that year on. Order matters:
# more specific words first ("rebuilt" contains "built").
STATE_AFTER = [
    (("reconstruction", "rebuilding", "restoration"), "under reconstruction"),
    (("burnt", "burned", "fire", "brand", "destroyed", "demolished"), "burnt, only the base left"),
    (("rebuilt", "reopened", "reconstructed"), "rebuilt"),
    (("restored", "renovated", "redecorated", "decorated", "decoration"), "restored"),
    (("built", "opened", "completed"), "standing"),
    (("extended", "extension", "steam"), "standing, extended"),
    (("damaged", "storm"), "standing, damaged"),
    (("repurposed", "converted", "conversion"), "repurposed"),
]

# User-written and aggregator sites: may confirm a claim, never its only source.
WEAK_NAMES = frozenset(
    {
        "tripadvisor",
        "yelp",
        "foursquare",
        "facebook",
        "instagram",
        "tiktok",
        "twitter",
        "reddit",
        "quora",
        "pinterest",
        "aroundus",
        "wanderlog",
        "tripomatic",
        "sygic",
        "inspirock",
        "triphobo",
        "getyourguide",
        "viator",
        "expedia",
        "booking",
        "airbnb",
        "klook",
        "musement",
        "tiqets",
    }
)


class ResearchError(Exception):
    """The research step failed or returned unusable data."""


def fetch_facts(qid, get=None, sleep=time.sleep, lang="en"):
    """Structured facts for the confirmed object. `get` is injectable."""
    get = get or requests.get
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels",
                "languages": "nl|en",
                "format": "json",
            },
            sleep=sleep,
        )
    except WebError as exc:
        raise ResearchError(str(exc))
    entity = data["entities"][qid]
    claims = entity.get("claims", {})
    need = set()
    for prop in FACT_PROPS:
        for stmt in claims.get(prop, []):
            need |= _item_ids(stmt.get("mainsnak", {}))
            for qual in (stmt.get("qualifiers", {}) or {}).values():
                for q in qual:
                    need |= _item_ids(q)
            for ref in stmt.get("references", []) or []:
                for snaks in (ref.get("snaks", {}) or {}).values():
                    for s in snaks:
                        need |= _item_ids(s)
    try:
        labels = _entity_labels(sorted(need), get, sleep, lang) if need else {}
    except WebError as exc:
        raise ResearchError(str(exc))
    facts = []
    for prop, name in FACT_PROPS.items():
        for stmt in claims.get(prop, []):
            facts.append(
                {
                    "property": prop,
                    "name": name,
                    "value": _snak_value(stmt.get("mainsnak", {}), labels),
                    "qualifiers": {
                        p: [_snak_value(s, labels) for s in snaks]
                        for p, snaks in (stmt.get("qualifiers", {}) or {}).items()
                    },
                    "references": [
                        {
                            p: [_snak_value(s, labels) for s in snaks]
                            for p, snaks in (ref.get("snaks", {}) or {}).items()
                        }
                        for ref in stmt.get("references", []) or []
                    ],
                    "source": f"https://www.wikidata.org/wiki/{qid}#{prop}",
                }
            )
    lang_labels = entity.get("labels", {})
    best = _pick_label(lang_labels, lang)
    return {
        "qid": qid,
        "label": best,
        "facts": facts,
        "commons_category": next(
            (f["value"] for f in facts if f["property"] == "P373"), None
        ),
        "image": next((f["value"] for f in facts if f["property"] == "P18"), None),
    }


def _entity_labels(qids, get, sleep=time.sleep, lang="en") -> dict:
    langs = "|".join(dict.fromkeys([lang, "en", "nl"]))
    data = mediawiki_get(
        get,
        "https://www.wikidata.org/w/api.php",
        {
            "action": "wbgetentities",
            "ids": "|".join(qids[:50]),
            "props": "labels",
            "languages": langs,
            "format": "json",
        },
        sleep=sleep,
    )
    out = {}
    for qid, entity in data.get("entities", {}).items():
        out[qid] = _pick_label(entity.get("labels", {}), lang) or qid
    return out


def _pick_label(labels: dict, lang: str) -> str | None:
    """Label in the user's language, English fallback, then anything."""
    for code in dict.fromkeys([lang, "en", "nl", *labels]):
        if labels.get(code):
            return labels[code]["value"]
    return None


def _item_ids(snak: dict) -> set:
    dv = snak.get("datavalue", {}) or {}
    if dv.get("type") == "wikibase-entityid":
        return {dv["value"]["id"]}
    return set()


def _snak_value(snak: dict, labels: dict):
    dv = snak.get("datavalue", {}) or {}
    if dv.get("type") == "wikibase-entityid":
        qid = dv["value"]["id"]
        return {"qid": qid, "label": labels.get(qid, qid)}
    if dv.get("type") == "time":
        return {"time": dv["value"]["time"], "precision": dv["value"]["precision"]}
    return dv.get("value")


def lifespan_question(name, place, articles, lang="en") -> str:
    """Object-life question; the user's language article first when known."""
    where = f" in {place}" if place else ""
    ordered = sorted(articles, key=lambda code: (code != lang, code))
    reading = [
        f"https://{code}.wikipedia.org/wiki/{articles[code].replace(' ', '_')}"
        for code in ordered
    ]
    start = (
        f"Start from {' and '.join(reading)} and verify with other sources. "
        if reading
        else ""
    )
    return (
        f"What happened to the {name}{where} itself over its lifetime: "
        "when was it built, and was it ever extended, damaged, burnt, "
        "demolished, moved, restored, repurposed or rebuilt? Give the year of "
        f"each change. {start}State only what the sources say. Do not narrate "
        "your steps; answer with the JSON object only."
    )


def ask_lifespan(respond, question) -> dict:
    """One web_search plus structured-output call; last message only."""
    response = respond(question)
    messages = [o for o in response.get("output", []) if o.get("type") == "message"]
    if not messages:
        raise ResearchError("answer has no messages")
    last = messages[-1]["content"][0]
    import json

    try:
        parsed = json.loads(last["text"])
        events, sources = parsed["events"], parsed["sources"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ResearchError(f"final message is not a lifespan object: {exc}")
    citations = [
        {"url": a["url"], "title": a.get("title")}
        for a in last.get("annotations", [])
        if a.get("type") == "url_citation"
    ]
    snippets = [
        f"{r.get('url')}: {r['snippet'].strip()}"
        for o in response.get("output", [])
        if o.get("type") == "web_search_call"
        for r in o.get("results", []) or []
        if (r.get("snippet") or "").strip()
    ]
    return {"events": events, "sources": sources, "citations": citations, "snippets": snippets}


def build_timeline(events: list) -> list:
    """Sorted life events to clean {from_year, to_year, state} segments.

    One segment per distinct year (the last event of the year wins);
    planned-but-prevented changes leave no segment; adjacent equal states
    merge. Periods never overlap.
    """
    by_year: dict = {}
    for event in sorted(events, key=lambda e: e["year"]):
        state = _state_after(event["event"], event.get("detail", ""))
        if state is not None:
            by_year[event["year"]] = state
    merged = []
    for year in sorted(by_year):
        if merged and merged[-1]["state"] == by_year[year]:
            continue
        merged.append({"from_year": year, "to_year": None, "state": by_year[year]})
    for seg, nxt in zip(merged, merged[1:]):
        seg["to_year"] = nxt["from_year"]
    return merged


def _state_after(event: str, detail: str = "") -> str | None:
    words = set(re.findall(r"[a-z]+", event.lower()))
    lowered = detail.lower()
    if re.search(r"\b(prevented|averted|called off)\b", lowered) or (
        re.search(r"\b(planned|proposed|considered)\b", lowered)
        and not re.search(r"\b(start|started|began|complete|finished|opened|built|put in)\b", lowered)
    ):
        return None  # no change happened; leave no segment
    if ("tulip" in lowered or "tulp" in lowered) and any(
        k in words for k in ("decorated", "decoration", "extended", "restored", "beautified")
    ):
        return "decorated with tulips"
    for keywords, state in STATE_AFTER:
        if words & set(keywords):
            if state in ("rebuilt", "restored") and re.search(
                r"\b(start|started|began|under way|underway|first stone|first pole)\b",
                detail.lower(),
            ):
                return "under reconstruction"
            return state
    return event.strip().lower().replace("_", " ") or "stood"


def is_weak_source(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host == "x.com":
        return True
    return bool(WEAK_NAMES & set(host.split(".")))


def claim_quality_ok(urls: list) -> bool:
    """A claim needs at least one source that is not user-written."""
    return any(not is_weak_source(url) for url in urls)


PROPERTY_EVENTS = {"P571": "built", "P576": "demolished"}


def wikidata_claims(qid, facts) -> list:
    """Dated Wikidata statements become claims sourced to the item."""
    claims = []
    for fact in facts["facts"]:
        year = _statement_year(fact)
        if year is None:
            continue
        sources = [fact["source"]]
        for ref in fact["references"]:
            for values in ref.values():
                sources.extend(v for v in values if isinstance(v, str) and v.startswith("http"))
        event = PROPERTY_EVENTS.get(fact["property"], _short_value(fact["value"]))
        claims.append(
            {
                "year": year,
                "event": event,
                "kind": "object",
                "claim": f"{fact['name']}: {_short_value(fact['value'])}",
                "quote_span": None,
                "sources": sources,
            }
        )
    return claims


def _statement_year(fact) -> int | None:
    value = fact["value"]
    if isinstance(value, dict) and "time" in value:
        match = re.search(r"\+?(-?\d{1,4})-", value["time"])
        return int(match.group(1)) if match else None
    for prop in ("P585", "P580"):
        for qual in fact["qualifiers"].get(prop, []):
            if isinstance(qual, dict) and "time" in qual:
                match = re.search(r"\+?(-?\d{1,4})-", qual["time"])
                if match:
                    return int(match.group(1))
    return None


def _short_value(value) -> str:
    if isinstance(value, dict):
        return value.get("label") or value.get("time") or str(value)
    return str(value)


def assemble_claims(events, citations, sources) -> list:
    """Life events become object claims; answer-level sources deduped."""
    urls = sorted({c["url"] for c in citations} | set(sources))
    return [
        {
            "year": e["year"],
            "event": e["event"],
            "kind": "object",
            "claim": f"{e['event']}: {e['detail']}",
            "quote_span": e["detail"],
            "sources": urls,
        }
        for e in events
    ]
