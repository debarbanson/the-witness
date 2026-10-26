"""Probe: open sources for the Roelofarendsveen water tower (Q2487636).

a. Wikidata item facts: inception, architect, significant events, heritage
   designation, image and Commons category, with references.
b. Files in its Commons category with date and licence; PD or CC0 only.
c. Europeana search (reusability=open) for the tower and for
   Roelofarendsveen before 1990; PDM or CC0 rights only.
d. Follows the rules table: the doc User-Agent, one request at a time,
   raw responses kept in out/probes/ as the cache.

Saves wikidata_facts.json, commons_files.json, europeana.json and
references_summary.json (best dated image per era of the tower's film).
"""

import json
import os
import time

import requests

from probes.common import OUT, save_json

QID = "Q2487636"
USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"
EUROPEANA_URL = "https://api.europeana.eu/record/v2/search.json"
PD_RIGHTS = {
    "creativecommons.org/publicdomain/mark/1.0",
    "creativecommons.org/publicdomain/zero/1.0",
}

WANTED_PROPS = {
    "P571": "inception",
    "P84": "architect",
    "P793": "significant event",
    "P576": "demolished or destroyed",
    "P1435": "heritage designation",
    "P18": "image",
    "P373": "Commons category",
}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def get(url, params, pause=1.0):
    """One polite GET; returns parsed JSON. Retries once after 429/502."""
    time.sleep(pause)
    resp = _session.get(url, params=params, timeout=90)
    if resp.status_code in (429, 502):
        print(f"HTTP {resp.status_code} at {url}, waiting 30 s")
        time.sleep(30)
        resp = _session.get(url, params=params, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise SystemExit(f"API error at {url}: {data['error']}")
    return data


def main() -> None:
    facts = wikidata_facts()
    save_json("wikidata_facts.json", facts)
    print(f"wikidata: {len(facts['facts'])} fact groups from {QID}")

    category = facts["commons_category"]
    p18 = next((f["value"] for f in facts["facts"] if f["property"] == "P18"), None)
    files = commons_files(category, p18)
    save_json("commons_files.json", files)
    print(
        f"commons: category={files['category']} p18_kept={files['p18_kept']} "
        f"kept={len(files['kept'])} skipped={len(files['skipped'])}"
    )

    europeana = europeana_search()
    save_json("europeana.json", europeana)
    print(
        f"europeana: {europeana['queries'][0]['kept_count']} + "
        f"{europeana['queries'][1]['kept_count']} kept, "
        f"{europeana['queries'][0]['skipped_count']} + "
        f"{europeana['queries'][1]['skipped_count']} skipped"
    )

    summary = summarise(facts, files, europeana)
    save_json("references_summary.json", summary)
    print("best image per era:")
    for era, ref in summary["best_per_era"].items():
        print(f"- {era}: {ref}")


# --- a. Wikidata facts ------------------------------------------------------


def wikidata_facts() -> dict:
    data = get(
        "https://www.wikidata.org/w/api.php",
        {
            "action": "wbgetentities",
            "ids": QID,
            "props": "claims|labels",
            "languages": "nl|en",
            "format": "json",
        },
    )
    entity = data["entities"][QID]
    claims = entity.get("claims", {})

    need_labels = set()
    for prop in WANTED_PROPS:
        for stmt in claims.get(prop, []):
            need_labels |= _item_ids(stmt.get("mainsnak", {}))
            for qual in (stmt.get("qualifiers", {}) or {}).values():
                for q in qual:
                    need_labels |= _item_ids(q)
            for ref in stmt.get("references", []) or []:
                for snaks in (ref.get("snaks", {}) or {}).values():
                    for s in snaks:
                        need_labels |= _item_ids(s)
    labels = entity_labels(sorted(need_labels)) if need_labels else {}

    facts = []
    for prop, name in WANTED_PROPS.items():
        for stmt in claims.get(prop, []):
            facts.append(
                {
                    "property": prop,
                    "name": name,
                    "value": _snak_value(stmt.get("mainsnak", {}), labels),
                    "qualifiers": _qualifiers(stmt, labels),
                    "references": _references(stmt, labels),
                    "source": f"https://www.wikidata.org/wiki/{QID}#{prop}",
                }
            )
    category = next(
        (f["value"] for f in facts if f["property"] == "P373"), None
    )
    return {
        "qid": QID,
        "label": _label(entity.get("labels", {})),
        "facts": facts,
        "commons_category": category,
        "raw_claims": {p: claims[p] for p in WANTED_PROPS if p in claims},
    }


def entity_labels(qids: list) -> dict:
    data = get(
        "https://www.wikidata.org/w/api.php",
        {
            "action": "wbgetentities",
            "ids": "|".join(qids[:50]),
            "props": "labels",
            "languages": "nl|en",
            "format": "json",
        },
    )
    out = {}
    for qid, entity in data.get("entities", {}).items():
        out[qid] = _label(entity.get("labels", {}))
    return out


def _label(labels: dict) -> str | None:
    best = labels.get("nl") or labels.get("en")
    return best["value"] if best else None


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


def _qualifiers(stmt: dict, labels: dict) -> dict:
    out = {}
    for prop, snaks in (stmt.get("qualifiers", {}) or {}).items():
        out[prop] = [_snak_value(s, labels) for s in snaks]
    return out


def _references(stmt: dict, labels: dict) -> list:
    out = []
    for ref in stmt.get("references", []) or []:
        snaks = {}
        for prop, items in (ref.get("snaks", {}) or {}).items():
            snaks[prop] = [_snak_value(s, labels) for s in items]
        out.append(snaks)
    return out


# --- b. Commons category ----------------------------------------------------


def commons_files(category: str | None, p18: str | None) -> dict:
    """P18 file plus the files in the P373 category (or the P18 file's own)."""
    p18_record, p18_kept = None, False
    if p18:
        p18_record = file_record(f"File:{p18}")
        p18_kept = bool(p18_record and _is_open(p18_record["licence"]))
        if not category and p18_record:
            category = _p18_category(f"File:{p18}")
    kept, skipped = [], []
    if category:
        for page in _category_files(category):
            record = _file_record_from_page(page)
            (kept if _is_open(record["licence"]) else skipped).append(record)
        for record in skipped:
            record["reason"] = "licence not PD or CC0"
    return {
        "category": category,
        "p18": p18_record,
        "p18_kept": p18_kept,
        "kept": kept,
        "skipped": skipped,
    }


def file_record(title: str) -> dict | None:
    data = get(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "format": "json",
        },
    )
    pages = (data.get("query", {}).get("pages", {}) or {}).values()
    for page in pages:
        if "missing" in page:
            return None
        return _file_record_from_page(page)
    return None


def _p18_category(file_title: str) -> str | None:
    """Best category of the P18 file: one naming the place, else the first."""
    data = get(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "titles": file_title,
            "prop": "categories",
            "cllimit": 50,
            "format": "json",
        },
    )
    pages = list((data.get("query", {}).get("pages", {}) or {}).values())
    cats = [c["title"].removeprefix("Category:") for c in pages[0].get("categories", [])]
    cats = [c for c in cats if "tower" in c.lower() or "oelofarendsveen" in c.lower()] or cats
    return cats[0] if cats else None


def _category_files(category: str) -> list:
    out, cont = [], None
    while True:
        params = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": f"Category:{category}",
            "gcmtype": "file",
            "gcmlimit": 500,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "format": "json",
        }
        if cont:
            params["gcmcontinue"] = cont
        data = get("https://commons.wikimedia.org/w/api.php", params)
        out.extend((data.get("query", {}).get("pages", {}) or {}).values())
        cont = (data.get("continue", {}) or {}).get("gcmcontinue")
        if not cont:
            return out


def _file_record_from_page(page: dict) -> dict:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {}) or {}
    licence = (meta.get("LicenseShortName") or {}).get("value", "?")
    date = (meta.get("DateTimeOriginal") or {}).get("value") or (
        meta.get("DateTime") or {}
    ).get("value")
    return {
        "title": page["title"],
        "url": info.get("url"),
        "size": [info.get("width"), info.get("height")],
        "licence": licence,
        "date": (date or "?")[:60],
    }


def _is_open(licence: str) -> bool:
    return licence == "CC0" or "public domain" in licence.lower()


# --- c. Europeana -----------------------------------------------------------


def europeana_search() -> dict:
    key = os.environ.get("EUROPEANA_API_KEY")
    if not key:
        raise SystemExit("EUROPEANA_API_KEY is not set")
    queries = [
        {"label": "tower", "query": "watertoren Roelofarendsveen", "before": None},
        {"label": "place before 1990", "query": "Roelofarendsveen", "before": 1990},
    ]
    out = {"queries": []}
    for spec in queries:
        items, total, start = [], None, 1
        while total is None or start <= min(total, 300):
            params = {
                "wskey": key,
                "query": spec["query"],
                "qf": "TYPE:IMAGE",
                "reusability": "open",
                "rows": 50,
                "start": start,
                "profile": "rich",
            }
            data = get(EUROPEANA_URL, params)
            if total is None:
                total = data.get("totalResults", 0)
            page = data.get("items", []) or []
            if not page:
                break
            items.extend(page)
            start += len(page)
        kept, skipped = [], []
        for item in items:
            year = item.get("year")
            if spec["before"] is not None and year:
                try:
                    if int(str(year[0])[:4]) >= spec["before"]:
                        skipped.append(_eu_stub(item, "dated 1990 or later"))
                        continue
                except (ValueError, IndexError):
                    pass
            rights = _eu_rights(item)
            if rights in PD_RIGHTS:
                kept.append(_eu_record(item, rights))
            else:
                skipped.append(_eu_stub(item, f"rights not PD or CC0 ({rights})"))
        out["queries"].append(
            {
                "label": spec["label"],
                "query": spec["query"],
                "total_results": total,
                "returned": len(items),
                "kept": kept,
                "skipped": skipped,
            }
        )
    # Rename counts for the summary print (lists stay in the file).
    for q in out["queries"]:
        q["kept_count"] = len(q["kept"])
        q["skipped_count"] = len(q["skipped"])
    return out


def _eu_rights(item: dict) -> str:
    rights = item.get("rights") or item.get("edmRights") or []
    first = rights[0] if rights else "?"
    return first.replace("https://", "").replace("http://", "").rstrip("/")


def _eu_record(item: dict, rights: str) -> dict:
    return {
        "title": (item.get("title") or ["?"])[0][:200],
        "date": item.get("year") or item.get("dcDate"),
        "rights": rights,
        "provider": item.get("dataProvider"),
        "provider_link": item.get("edmIsShownAt"),
        "europeana_link": item.get("guid"),
        "thumbnail": item.get("edmPreview"),
    }


def _eu_stub(item: dict, reason: str) -> dict:
    return {
        "title": str((item.get("title") or ["?"])[0])[:120],
        "date": item.get("year"),
        "reason": reason,
    }


# --- summary ----------------------------------------------------------------


def summarise(facts: dict, files: dict, europeana: dict) -> dict:
    timeline = json.loads((OUT / "object_life_tower.json").read_text())["timeline"]
    dated = []
    for f in files["kept"]:
        year = _year_of(f["date"])
        if year:
            dated.append((year, f"commons:{f['title']} ({f['date'][:24]})"))
    for q in europeana["queries"]:
        for item in q["kept"]:
            year = _year_of(str(item.get("date") or ""))
            if year:
                dated.append((year, f"europeana:{item['title'][:80]}"))
    best = {}
    for seg in timeline:
        label = f"{seg['from_year']} to {seg['to_year']}: {seg['state']}"
        inside = [
            (y, ref) for y, ref in dated if seg["from_year"] <= y < (seg["to_year"] or 9999)
        ]
        best[label] = f"{len(inside)} dated reference(s)" + (
            f", e.g. {inside[0][1]}" if inside else ""
        )
    return {
        "facts": len(facts["facts"]),
        "commons_kept": len(files["kept"]),
        "commons_skipped": len(files["skipped"]),
        "europeana_kept": sum(q["kept_count"] for q in europeana["queries"]),
        "europeana_skipped": sum(q["skipped_count"] for q in europeana["queries"]),
        "best_per_era": best,
    }


def _year_of(text: str) -> int | None:
    import re

    m = re.search(r"\b(1[789]\d\d|20\d\d)\b", text or "")
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    main()
