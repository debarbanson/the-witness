"""Command line: identify a photo's object, research its history."""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

from witness import identify, models, outcome, research, verify

BASE_URL = "https://api.meta.ai/v1"


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
        return cmd_identify(args.photo, place=args.place, yes=args.yes)
    return cmd_research(args.photo, place=args.place, lang=args.lang, yes=args.yes)


def cmd_identify(photo, place=None, yes=False):
    try:
        found = identify.identify(photo, place=place, respond=vision_respond)
    except identify.NotIdentifiedError as exc:
        print(f"not identified: {exc}")
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


def cmd_research(photo, place=None, lang="en", yes=False):
    try:
        found = identify.identify(photo, place=place, respond=vision_respond)
    except identify.NotIdentifiedError as exc:
        print(f"object: not identified ({exc})")
        print("outcome: not_identified")
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
        facts = research.fetch_facts(found.qid, lang=lang)
        claims.extend(research.wikidata_claims(found.qid, facts))
        print(f"wikidata facts: {len(facts['facts'])} statements, {len(claims)} dated claims")
    question = research.lifespan_question(found.name, place or "", found.articles, lang=lang)
    answer = research.ask_lifespan(lifespan_respond, question)
    claims.extend(research.assemble_claims(answer["events"], answer["citations"], answer["sources"]))
    print(f"lifespan events: {len(answer['events'])}")

    kept = [c for c in claims if research.claim_quality_ok(c["sources"])]
    for c in claims:
        if not research.claim_quality_ok(c["sources"]):
            print(f"dropped (weak sources only): {c['year']} {c['claim'][:80]}")

    article_urls = [
        f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        for lang, title in found.articles.items()
    ]
    all_urls = sorted({u for c in kept for u in c["sources"]} | set(article_urls))
    texts = {}
    for url in all_urls:
        try:
            texts[url] = verify.fetch_source_text(url)
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            print(f"note: could not read {url} ({str(exc)[:100]})")

    for claim in kept:
        keywords = verify.keywords_for_claim(claim["claim"], claim.get("event", ""))
        evidence = list(answer["snippets"])
        for url, text in texts.items():
            for para in verify.select_paragraphs(text, claim["year"], keywords, max_paras=3):
                evidence.append(f"{url}\n{para}")
        evidence = evidence[:13]
        if not evidence:
            claim.update({"verdict": "unsupported", "quote": "", "rewritten": None,
                          "war_politics_only": False, "note": "no source text"})
            continue
        result = verify.verify_claim(verify_respond, claim["claim"], evidence)
        claim.update(result)
        claim["war_politics_only"] = claim["war_politics_only"] or bool(verify.flag_content(claim["claim"]))

    events = [
        {"year": c["year"], "event": c.get("event", "stood"), "detail": c.get("rewritten") or c.get("quote_span") or c["claim"]}
        for c in kept
        if c["verdict"] == "supported" or (c["verdict"] == "partly" and c["rewritten"])
    ]
    timeline = research.build_timeline(events)
    result = outcome.decide(
        [
            {**c, "event": c.get("event", "stood")}
            for c in kept
            if c["verdict"] == "supported" or (c["verdict"] == "partly" and c["rewritten"])
        ],
        identified=True,
    )

    print("\nclaims:")
    for c in kept:
        print(f"- {c['year']} [{c['verdict']}] {c['claim'][:120]}")
        for url in c["sources"]:
            print(f"    source: {url}")
        if c.get("quote"):
            print(f"    quote: {c['quote'][:150]}")
        if c.get("url"):
            print(f"    quote from: {c['url']}")
        if c["verdict"] == "partly" and c.get("rewritten"):
            print(f"    rewritten: {c['rewritten'][:120]}")
    print("\ntimeline:")
    for seg in timeline:
        print(f"- {seg['from_year']} to {seg['to_year']}: {seg['state']}")
    print(f"\noutcome: {result['outcome']} ({result['reason']}; "
          f"{result['verified']} verified, {result['eras']} eras, {result['good_sources']} good sources)")

    slug = re.sub(r"[^a-z0-9]+", "-", found.name.lower()).strip("-") or "film"
    out_dir = Path("out") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research.json").write_text(
        json.dumps(
            {
                "object": {"name": found.name, "kind": found.kind, "qid": found.qid, "articles": found.articles},
                "claims": kept,
                "timeline": timeline,
                "outcome": result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"saved: {out_dir / 'research.json'}")
    return 0


def _client():
    from openai import OpenAI

    key = os.environ.get("MODEL_API_KEY")
    if not key:
        print("MODEL_API_KEY is not set", file=sys.stderr)
        raise SystemExit(1)
    return OpenAI(base_url=BASE_URL, api_key=key)


def vision_respond(prompt, jpeg_bytes):
    uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
    resp = _client().responses.create(
        model="muse-spark-1.3",
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": uri},
        ]}],
    )
    return json.loads(resp.model_dump_json())


def lifespan_respond(question):
    resp = _client().responses.create(
        model="muse-spark-1.3",
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        text={"format": {"type": "json_schema", "name": "object_life",
                         "schema": research.LIFESPAN_SCHEMA, "strict": True}},
        input=question,
    )
    return json.loads(resp.model_dump_json())


def verify_respond(prompt):
    try:
        client = models.client_for(models.VERIFY)
    except models.ModelError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
    resp = client.responses.create(
        model=models.VERIFY.model,
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        input=prompt,
    )
    return json.loads(resp.model_dump_json())


if __name__ == "__main__":
    raise SystemExit(main())
