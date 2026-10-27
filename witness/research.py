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

from witness import states
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
                    "visible_change": {"type": "string"},
                    "date_text": {"type": "string"},
                },
                "required": ["year", "event", "detail", "visible_change", "date_text"],
                "additionalProperties": False,
            },
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["events", "sources"],
    "additionalProperties": False,
}



# Wikipedia languages per country (Nominatim country codes): research reads
# these first, then the user's language, then English.
LOCAL_LANGS = {
    "nl": ["nl"], "be": ["nl", "fr"], "dk": ["da"], "jp": ["ja"], "gb": ["en"],
    "us": ["en"], "br": ["pt"], "ca": ["fr", "en"], "fr": ["fr"], "ml": ["fr"],
    "au": ["en"], "sg": ["en"], "de": ["de"], "es": ["es", "ca"], "it": ["it"],
    "pt": ["pt"], "se": ["sv"],
}


def read_langs(country_code, user_lang="en") -> list:
    """Article reading order: local languages, user language, English."""
    local = LOCAL_LANGS.get((country_code or "").lower(), [])
    return list(dict.fromkeys([*local, user_lang, "en"]))


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


def fetch_facts(qid, get=None, sleep=time.sleep, lang="en", cache=None, country_code=None):
    """Structured facts for the confirmed object. `get` is injectable."""
    get = get or requests.get
    order = read_langs(country_code, lang)
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels",
                "languages": "|".join(order),
                "format": "json",
            },
            sleep=sleep,
            cache=cache,
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
        labels = _entity_labels(sorted(need), get, sleep, order, cache) if need else {}
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
    best = _pick_label(lang_labels, order)
    return {
        "qid": qid,
        "label": best,
        "facts": facts,
        "commons_category": next(
            (f["value"] for f in facts if f["property"] == "P373"), None
        ),
        "image": next((f["value"] for f in facts if f["property"] == "P18"), None),
    }


def _entity_labels(qids, get, sleep=time.sleep, order=("en",), cache=None) -> dict:
    langs = "|".join(order)
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
        cache=cache,
    )
    out = {}
    for qid, entity in data.get("entities", {}).items():
        out[qid] = _pick_label(entity.get("labels", {}), order) or qid
    return out


def _pick_label(labels: dict, order) -> str | None:
    """Label in reading order (local languages, user language, English)."""
    for code in dict.fromkeys([*order, *labels]):
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


def lifespan_question(name, place, articles, read_langs=("en",)) -> str:
    """Object-life question; articles ordered by the reading languages."""
    where = f" in {place}" if place else ""
    order = list(read_langs)
    ordered = sorted(articles, key=lambda code: (code not in order, order.index(code) if code in order else 0, code))
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
        f"each change. {start}For each change give visible_change: what "
        "visibly changed about the object's appearance (for example 'sails "
        "replaced', 'height raised', 'repainted'); empty string when the "
        "event did not change what the object looks like. When the sources "
        "give only a vague date, put it in date_text (for example 'in the "
        "1960s' or 'about 800 years old') and give your best year for "
        "sorting only. When the sources give an age or date as a range, "
        "keep the range as stated in date_text (for example 'between 800 "
        "and 1,200 years old'); never collapse a range to one precise "
        "year. State only what the sources say. Do not narrate "
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
    uncompleted and partly verified changes leave no segment; adjacent
    identical states merge. Periods never overlap.
    """
    by_year: dict = {}
    detail_of: dict = {}
    label_of: dict = {}
    previous = None
    for event in sorted(events, key=lambda e: e["year"]):
        if event.get("verdict", "supported") != "supported":
            continue
        if not event.get("completed", True):
            continue
        state = states.classify(
            event["event"], event.get("detail", ""),
            event.get("visible_change", ""), previous,
        )
        if state is not None:
            by_year[event["year"]] = state
            detail_of[event["year"]] = event.get("detail", "")
            label_of[event["year"]] = states.date_label(
                event.get("date_text", ""), event["year"])
            previous = state["condition"]
    merged = []
    for year in sorted(by_year):
        if merged and merged[-1]["state"] == by_year[year]:
            continue
        merged.append({"from_year": year, "to_year": None, "state": by_year[year],
                       "date_label": label_of[year]})
    for seg, nxt in zip(merged, merged[1:]):
        seg["to_year"] = nxt["from_year"]
    for seg, nxt in zip(merged, [*merged[1:], None]):
        flag = states.check_span(
            seg["state"]["condition"], seg["from_year"], seg["to_year"],
            detail_of.get(seg["from_year"], ""),
            nxt["state"]["condition"] if nxt else None,
        )
        if flag is not None:
            seg["flag"] = flag
    return merged


def is_weak_source(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host == "x.com":
        return True
    return bool(WEAK_NAMES & set(host.split(".")))


def claim_quality_ok(urls: list) -> bool:
    """A claim needs at least one source that is not user-written."""
    return any(not is_weak_source(url) for url in urls)


PROPERTY_EVENTS = {
    "P571": "built",
    "P576": "demolished",
    "P18": "image",
    "P84": "architect",
    "P1435": "heritage designation",
}


def wikidata_claims(qid, facts) -> list:
    """Dated Wikidata statements become claims sourced to the item.

    Dates follow the statement's precision; raw timestamps never reach
    claim text. State vs caption is decided later by meaning, never by
    property: thing facts are simply named as what they are.
    """
    claims = []
    for fact in facts["facts"]:
        dated = _statement_date(fact)
        if dated is None:
            continue
        year, date_text = dated
        if not sane_year(year):
            continue
        sources = [fact["source"]]
        for ref in fact["references"]:
            for values in ref.values():
                sources.extend(v for v in values if isinstance(v, str) and v.startswith("http"))
        event = PROPERTY_EVENTS.get(fact["property"], _short_value(fact["value"]))
        if fact["property"] in ("P571", "P576", "P793"):
            text = f"{event} {date_text}"
        else:
            text = f"{event}: {_short_value(fact['value'])}"
        claims.append(
            {
                "year": year,
                "event": event,
                "kind": "object",
                "claim": text,
                "quote_span": None,
                "date_text": date_text,
                "visible_change": "",
                "sources": sources,
            }
        )
    return claims


def _statement_date(fact) -> tuple | None:
    """Nominal year for sorting plus the precision-aware date phrase."""
    value = fact["value"]
    if isinstance(value, dict) and "time" in value:
        return _dated(value["time"], value.get("precision", 9))
    for prop in ("P585", "P580"):
        for qual in fact["qualifiers"].get(prop, []):
            if isinstance(qual, dict) and "time" in qual:
                return _dated(qual["time"], qual.get("precision", 9))
    return None


def _dated(time_value: str, precision: int) -> tuple | None:
    match = re.search(r"\+?(-?\d{1,4})-", time_value)
    if not match:
        return None
    return int(match.group(1)), states.format_wikidate(time_value, precision)


def _short_value(value) -> str:
    if isinstance(value, dict):
        return value.get("label") or value.get("time") or str(value)
    return str(value)


OLDEST_YEAR = -10000  # older than any object a film can show


def sane_year(year) -> bool:
    """Model years stay inside history: no geology, no far future."""
    from datetime import date

    return (isinstance(year, int) and not isinstance(year, bool)
            and OLDEST_YEAR <= year <= date.today().year + 1)


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
            "date_text": e.get("date_text", ""),
            "visible_change": e.get("visible_change", ""),
            "sources": urls,
        }
        for e in events
        if sane_year(e.get("year"))
    ]
