"""Command line: identify a photo's object, research its history."""

import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from witness import identify, models, outcome, research, scenes, verify
from witness.cache import Cache


def main(argv=None):
    parser = argparse.ArgumentParser(prog="witness")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("identify", "research"):
        cmd = sub.add_parser(name)
        cmd.add_argument("photo")
        cmd.add_argument("--place", default=None)
        cmd.add_argument("--lang", default="en")
        cmd.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "identify":
        return cmd_identify(args.photo, place=args.place, lang=args.lang, yes=args.yes)
    return cmd_research(args.photo, place=args.place, lang=args.lang, yes=args.yes)


def cmd_identify(photo, place=None, lang="en", yes=False):
    try:
        found = identify.identify(photo, place=place, respond=vision_respond, cache=Cache("out/cache"), lang=lang)
    except identify.NotIdentifiedError as exc:
        print(f"not identified: {exc}")
        return 2
    except identify.SourceError as exc:
        print(f"source failed: {exc}")
        return 2
    print(f"object: {found.name} ({found.kind})")
    print(f"distance: about {found.distance_m} m")
    if found.qid:
        print(f"wikidata: https://www.wikidata.org/wiki/{found.qid}")
    for lang, title in found.articles.items():
        print(f"article [{lang}]: https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}")
    print(f"confidence: {found.confidence}")
    if not yes:
        answer = input(f"Is this {found.name}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("not confirmed; stopping")
            return 2
    return 0


SPARES = 4  # extra claims verified outside the draft scenes


def cmd_research(photo, place=None, lang="en", yes=False):
    cache = Cache("out/cache")
    timings = {}
    start = time.perf_counter()
    try:
        phase = time.perf_counter()
        found = identify.identify(photo, place=place, respond=vision_respond, cache=cache, lang=lang)
        timings["identify_s"] = round(time.perf_counter() - phase, 1)
    except identify.NotIdentifiedError as exc:
        print(f"object: not identified ({exc})")
        print("outcome: not_identified")
        return 2
    except identify.SourceError as exc:
        print(f"source failed: {exc}")
        return 2
    print(f"object: {found.name} ({found.kind})")
    if found.qid:
        print(f"wikidata: https://www.wikidata.org/wiki/{found.qid}")
    if not yes:
        answer = input(f"Is this {found.name}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("not confirmed; stopping")
            return 2

    claims = []
    if found.qid:
        phase = time.perf_counter()
        facts = research.fetch_facts(found.qid, lang=lang, cache=cache)
        claims.extend(research.wikidata_claims(found.qid, facts))
        timings["facts_s"] = round(time.perf_counter() - phase, 1)
        print(f"wikidata facts: {len(facts['facts'])} statements, {len(claims)} dated claims")
    phase = time.perf_counter()
    question = research.lifespan_question(
        found.name, place or "", found.articles,
        read_langs=research.read_langs(found.country_code, lang),
    )
    answer = research.ask_lifespan(lifespan_respond, question)
    timings["research_s"] = round(time.perf_counter() - phase, 1)
    claims.extend(research.assemble_claims(answer["events"], answer["citations"], answer["sources"]))
    print(f"lifespan events: {len(answer['events'])}")

    kept = [c for c in claims if research.claim_quality_ok(c["sources"])]
    for c in claims:
        if not research.claim_quality_ok(c["sources"]):
            print(f"dropped (weak sources only): {c['year']} {c['claim'][:80]}")

    # Choose before checking: draft scenes from unverified claims, then
    # verify only what the scenes need plus a few spares.
    draft_events = [
        {"year": c["year"], "event": c.get("event", "stood"), "detail": c.get("quote_span") or c["claim"],
         "visible_change": c.get("visible_change", "")}
        for c in kept
    ]
    draft = scenes.choose_scenes(research.build_timeline(draft_events), kept)
    scene_years = {s["from_year"] for s in draft if isinstance(s["from_year"], int)}
    to_check = [c for c in kept if c["year"] in scene_years]
    spares = [c for c in kept if c["year"] not in scene_years][:SPARES]
    for c in kept:
        if c not in to_check and c not in spares:
            c.update({"verdict": "unverified", "quote": "", "url": None, "support": [],
                      "note": "outside chosen scenes", "completed": True,
                      "rewritten": None, "war_politics_only": False})
    print(f"checking {len(to_check) + len(spares)} of {len(kept)} claims ({len(spares)} spares)")

    article_urls = [
        f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        for lang, title in found.articles.items()
    ]
    all_urls = sorted({u for c in to_check + spares for u in c["sources"]} | set(article_urls))
    phase = time.perf_counter()
    texts = {}
    for url in all_urls:
        try:
            texts[url] = verify.fetch_source_text(url, cache=cache)
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            print(f"note: could not read {url} ({str(exc)[:100]})")
    timings["fetch_s"] = round(time.perf_counter() - phase, 1)

    jobs = []
    for claim in to_check + spares:
        keywords = verify.keywords_for_claim(claim["claim"], claim.get("event", ""))
        evidence = list(answer["snippets"])
        for url, text in texts.items():
            for para in verify.select_paragraphs(text, claim["year"], keywords, max_paras=3):
                evidence.append(f"{url}\n{para}")
        jobs.append((claim["claim"], evidence[:13]))
    phase = time.perf_counter()
    for claim, result in zip(to_check + spares, verify.verify_all(verify_respond, jobs)):
        claim.update(result)
        claim["war_politics_only"] = claim["war_politics_only"] or bool(verify.flag_content(claim["claim"]))
    timings["verify_s"] = round(time.perf_counter() - phase, 1)

    verified = [c for c in kept if c["verdict"] == "supported" or (c["verdict"] == "partly" and c["rewritten"])]
    events = [
        {"year": c["year"], "event": c.get("event", "stood"), "detail": c.get("rewritten") or c.get("quote_span") or c["claim"],
         "completed": c.get("completed", True), "verdict": c.get("verdict", "supported"),
         "visible_change": c.get("visible_change", "")}
        for c in verified
    ]
    timeline = research.build_timeline(events)
    chosen = scenes.choose_scenes(timeline, verified)
    result = outcome.decide([{**c, "event": c.get("event", "stood")} for c in verified], identified=True)

    print("\nclaims:")
    for c in kept:
        print(f"- {c['year']} [{c['verdict']}] {c['claim'][:120]}")
        for url in c["sources"]:
            print(f"    source: {url}")
        if c.get("quote"):
            print(f"    quote: {c['quote'][:150]}")
        if c.get("url"):
            print(f"    quote from: {c['url']}")
        if c.get("note"):
            print(f"    note: {c['note']}")
        if c["verdict"] == "partly" and c.get("rewritten"):
            print(f"    rewritten: {c['rewritten'][:120]}")
    print("\nscenes:")
    for s in chosen:
        print(f"- {s['from_year']}: {_show_state(s['state'])} ({s['reason']})")
        for line in s["caption_lines"]:
            print(f"    line: {line['line'][:100]}")
    print("\ntimeline:")
    for seg in timeline:
        print(f"- {seg['from_year']} to {seg['to_year']}: {_show_state(seg['state'])}")
    print(f"\noutcome: {result['outcome']} ({result['reason']}; "
          f"{result['verified']} verified, {result['eras']} eras, {result['good_sources']} good sources)")

    slug = slug_for(found.name, found.qid, found.articles)
    out_dir = Path("out") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    timings["total_s"] = round(time.perf_counter() - start, 1)
    print(f"timings (s): {json.dumps(timings)}")
    (out_dir / "research.json").write_text(
        json.dumps(
            {
                "object": {"name": found.name, "kind": found.kind, "qid": found.qid, "articles": found.articles},
                "claims": kept,
                "timeline": timeline,
                "scenes": chosen,
                "outcome": result,
                "timings": timings,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"saved: {out_dir / 'research.json'}")
    return 0


def _show_state(state: dict) -> str:
    shown = state["condition"]
    if state.get("scope", "whole") != "whole":
        shown += f" ({state['scope']})"
    if state.get("degree", "total") != "total":
        shown += f" ({state['degree']})"
    if state.get("description"):
        shown += f": {state['description'][:80]}"
    return shown


def slug_for(name, qid, articles) -> str:
    """Filesystem slug in any script: transliterated name, else an article
    title, else the Wikidata id (e.g. q1196460-kintai-bridge)."""
    candidates = [name, *(articles.get(lang, "") for lang in ("en", "nl", "fr", "de"))]
    for text in candidates:
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
        if slug:
            return f"{qid.lower()}-{slug}" if qid else slug
    return qid.lower() if qid else "film"


def _respond_for(spec):
    try:
        return models.client_for(spec)
    except models.ModelError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)


def vision_respond(prompt, jpeg_bytes):
    uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
    resp = models.respond(
        _respond_for(models.VISION),
        models.VISION,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": uri},
        ]}],
    )
    return json.loads(resp.model_dump_json())


def lifespan_respond(question):
    resp = models.respond(
        _respond_for(models.RESEARCH),
        models.RESEARCH,
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        text={"format": {"type": "json_schema", "name": "object_life",
                         "schema": research.LIFESPAN_SCHEMA, "strict": True}},
        input=question,
    )
    return json.loads(resp.model_dump_json())


def verify_respond(prompt):
    resp = models.respond(
        _respond_for(models.VERIFY),
        models.VERIFY,
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        input=prompt,
    )
    return json.loads(resp.model_dump_json())


if __name__ == "__main__":
    raise SystemExit(main())
