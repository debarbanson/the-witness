"""Command line: identify a photo's object, research its history."""

import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from witness import identify, models, outcome, research, scenes, states, stream, verify
from witness.cache import Cache


def main(argv=None):
    parser = argparse.ArgumentParser(prog="witness")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("identify", "research", "film"):
        cmd = sub.add_parser(name)
        cmd.add_argument("photo")
        cmd.add_argument("--place", default=None)
        cmd.add_argument("--lang", default="en")
        cmd.add_argument("--yes", action="store_true")
        cmd.add_argument("--no-cache", action="store_true")
        if name == "research":
            cmd.add_argument("--verify-with", default="baseten",
                             choices=("meta", "baseten", "both"))
        if name == "film":
            cmd.add_argument("--verify-with", default="baseten",
                             choices=("meta", "baseten"))
    keep = sub.add_parser("keep")
    keep.add_argument("slug")
    args = parser.parse_args(argv)
    if args.command == "identify":
        return cmd_identify(args.photo, place=args.place, lang=args.lang,
                            yes=args.yes, no_cache=args.no_cache)
    if args.command == "keep":
        return cmd_keep(args.slug)
    if args.command == "film":
        return cmd_film(args.photo, place=args.place, lang=args.lang,
                        yes=args.yes, no_cache=args.no_cache,
                        verify_with=args.verify_with)
    return cmd_research(args.photo, place=args.place, lang=args.lang,
                        yes=args.yes, no_cache=args.no_cache,
                        verify_with=args.verify_with)


def cmd_keep(slug):
    """Owner-reviewed research for an object: kept, so demo films never flap."""
    path = Path("out") / slug / "research.json"
    if not path.exists():
        print(f"no research at {path}")
        return 2
    data = json.loads(path.read_text())
    qid, lang = data["object"].get("qid"), data["object"].get("lang", "en")
    if not qid:
        print("research has no Wikidata id; nothing kept")
        return 2
    Cache("out/cache").put_reviewed(qid, lang, data)
    print(f"kept reviewed research for {qid} ({lang})")
    return 0


def cmd_identify(photo, place=None, lang="en", yes=False, no_cache=False):
    cache = None if no_cache else Cache("out/cache")
    try:
        steps = {}
        found = identify.identify(photo, place=place, respond=vision_respond, cache=cache,
                                  lang=lang, timings=steps)
        print(f"identify steps (s): {json.dumps(steps)}")
    except identify.NotIdentifiedError as exc:
        print(f"identify steps (s): {json.dumps(steps)}")
        print(f"not identified: {exc}")
        return 2
    except identify.SourceError as exc:
        print(f"source failed: {exc}")
        return 2
    print(describe_found(found))
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


def cmd_film(photo, place=None, lang="en", yes=False, no_cache=False, verify_with="baseten",
             progress=None):
    """The film as a stream: opening card within seconds, then one ready
    scene after another. Research starts while the user still confirms."""
    filmed = stream.FilmStream()
    cache = None if no_cache else Cache("out/cache")
    models.reset_usage()
    timings = {}
    start = time.perf_counter()
    try:
        phase = time.perf_counter()
        identify_steps = {}
        found = identify.identify(photo, place=place, respond=vision_respond, cache=cache,
                                  lang=lang, timings=identify_steps, progress=progress)
        timings["identify_s"] = round(time.perf_counter() - phase, 1)
        timings["identify_steps"] = identify_steps
        print(f"identify steps (s): {json.dumps(identify_steps)}")
    except identify.NotIdentifiedError as exc:
        print(f"identify steps (s): {json.dumps(identify_steps)}")
        print(f"object: not identified ({exc})")
        print("outcome: not_identified")
        return 2
    except identify.SourceError as exc:
        print(f"source failed: {exc}")
        return 2
    print(describe_found(found))
    if found.qid:
        print(f"wikidata: https://www.wikidata.org/wiki/{found.qid}")
    order = research.read_langs(found.country_code, lang)
    if cache is not None and found.qid:
        slug = slug_for(found.name, found.qid, found.articles, prefer=order)
        reviewed = cache.get_reviewed(found.qid, lang)
        if reviewed is not None:
            out_path = Path("out") / slug / "research.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(reviewed, indent=2, ensure_ascii=False))
            result = reviewed.get("outcome", {})
            print(f"film opens instantly (reviewed research reused; use --no-cache to redo)")
            print(f"outcome: {result.get('outcome')}")
            return 0
        film = cached_film(slug)
        if film is not None:
            result = film.get("outcome", {})
            print(f"film opens instantly (cached film from {film.get('saved_at')}; "
                  f"use --no-cache to check again)")
            print(f"outcome: {result.get('outcome')}")
            return 0
    article_urls = [
        f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        for lang, title in found.articles.items()
    ]
    fetched = SourceTexts(cache=cache, progress=progress)
    support = baseten_support_respond if verify_with == "baseten" else support_respond
    workers = models.VERIFY_OPEN.workers if verify_with == "baseten" else models.VERIFY.workers

    def gather():
        phase = time.perf_counter()
        facts = (research.fetch_facts(found.qid, None, time.sleep, lang, cache,
                                      found.country_code)
                 if found.qid else {"facts": []})
        timings["facts_s"] = round(time.perf_counter() - phase, 1)
        claims = research.wikidata_claims(found.qid, facts) if found.qid else []
        print(f"wikidata facts: {len(facts['facts'])} statements, {len(claims)} dated claims")
        build_anchor_year = next((c["year"] for c in claims if c.get("anchor") == "build"), None)
        if build_anchor_year is not None:
            print(f"build anchor: {build_anchor_year} fixed by Wikidata")
        phase = time.perf_counter()
        question = research.lifespan_question(
            found.name, place or "", found.articles,
            read_langs=research.read_langs(found.country_code, lang))
        answer = research.ask_lifespan(lifespan_respond, question)
        timings["research_s"] = round(time.perf_counter() - phase, 1)
        modelled = research.assemble_claims(answer["events"], answer["citations"],
                                            answer["sources"], anchor_year=build_anchor_year)
        if len(modelled) < len(answer["events"]):
            print(f"dropped (anchor stands): {len(answer['events']) - len(modelled)} research build years")
        claims.extend(modelled)
        print(f"lifespan events: {len(answer['events'])}")
        kept = keep_quality(claims)
        to_check, pool = plan_checks(kept)
        for c in pool:
            c.update({"verdict": "unverified", "quote": "", "url": None, "support": [],
                      "note": "outside chosen scenes", "completed": True,
                      "rewritten": None, "war_politics_only": False})
        print(f"checking {len(to_check)} of {len(kept)} claims (spares on need)")
        draft = draft_scenes(kept)
        phase = time.perf_counter()
        fetched.fetch(to_check, article_urls, verify_with)
        timings["fetch_s"] = round(time.perf_counter() - phase, 1)
        anchor_year = min([c["year"] for c in kept], default=None)
        jobs = build_jobs(to_check, fetched.texts, answer["snippets"], anchor_year)
        return {"kept": kept, "to_check": to_check, "pool": pool, "draft": draft, "jobs": jobs}

    if yes:
        gathered = gather()
    else:
        before = models.usage_totals()

        def decide():
            answer = input(f"Is this {found.name}? [Y/n] ").strip().lower()
            return answer in ("", "y", "yes")

        confirmed, gathered = stream.confirm_speculative(f"Is this {found.name}?", gather, decide)
        if not confirmed:
            after = models.usage_totals()
            spent = sum(v.get("total_tokens", 0) for v in after.values()) - sum(
                v.get("total_tokens", 0) for v in before.values())
            print(f"not confirmed; speculative work discarded (cost: {spent} tokens)")
            return 2
    card = stream.opening_card(found.name, found.kind, gathered["kept"], photo)
    filmed.emit("opening_card", card)
    print(f"\n---\n{card['name']} ({card['kind']})")
    if card["text"]:
        print(card["text"])
    print("---")

    def emit_scene(scene_no, scene):
        filmed.emit("scene_verified", {"scene": scene_no, "year": scene["from_year"],
                                       "date_label": scene.get("date_label")})
        print(f"Scene {scene_no} ({scene.get('date_label', scene['from_year'])}) verified")

    phase = time.perf_counter()
    to_check, draft, jobs = gathered["to_check"], gathered["draft"], gathered["jobs"]
    judged_years: list = []
    emitted: set = set()
    to_check_years = [c["year"] for c in to_check]
    scene_no = 0
    for index, result in verify.judge_stream(support, jobs, search_respond=verify_respond,
                                             completion_respond=support,
                                             max_workers=workers, progress=progress):
        claim = to_check[jobs[index]["claim_index"]]
        claim.update(result)
        claim["war_politics_only"] = (
            claim["war_politics_only"] or bool(verify.flag_content(claim["claim"])))
        judged_years.append(claim["year"])
        for scene in stream.newly_ready_scenes(draft, judged_years, to_check_years, emitted):
            emitted.add(scene["from_year"])
            scene_no += 1
            emit_scene(scene_no, scene)
    fast = sum(1 for c in to_check if c.get("fast_path"))
    if fast:
        print(f"fast paths: {fast} of {len(to_check)} decided without a vote")
    timings["verify_s"] = round(time.perf_counter() - phase, 1)

    def refresh_film():
        film_verified = [c for c in gathered["kept"] if c["verdict"] == "supported"
                         or (c["verdict"] == "partly" and c["rewritten"])]
        film_timeline = research.build_timeline(timeline_events(film_verified))
        film_chosen = scenes.choose_scenes(film_timeline, film_verified)
        return film_verified, film_timeline, film_chosen

    verified, timeline, chosen = refresh_film()
    need = spare_needs(chosen, [c for c in gathered["pool"] if c["verdict"] == "unverified"])
    if need:
        spares = sorted([c for c in gathered["pool"] if c["verdict"] == "unverified"],
                        key=lambda c: states.classify(
                            c.get("event", "stood"), c.get("quote_span") or c["claim"])
                        is None)[:need]
        print(f"checking {len(spares)} spares for caption lines")
        phase = time.perf_counter()
        fetched.fetch(spares, article_urls, verify_with)
        timings["fetch_s"] = round(timings["fetch_s"] + time.perf_counter() - phase, 1)
        phase = time.perf_counter()
        spare_jobs = build_jobs(spares, fetched.texts, [], min([c["year"] for c in gathered["kept"]]))
        judged = verify.judge_all(support, spare_jobs, search_respond=verify_respond,
                                  completion_respond=support, max_workers=workers,
                                  progress=progress)
        apply_judged(spares, spare_jobs, judged)
        timings["verify_s"] = round(timings["verify_s"] + time.perf_counter() - phase, 1)
        verified, timeline, chosen = refresh_film()
    result = outcome.decide([{**c, "event": c.get("event", "stood")} for c in verified], identified=True)
    timings["total_s"] = round(time.perf_counter() - start, 1)
    report_and_save(found, lang, order, gathered["kept"], timeline, chosen, result,
                    timings, verify_with, fetched.failures, None,
                    stream_events=filmed.events)
    first_scene = filmed.metric("scene_verified")
    print(f"stream: opening card at {filmed.metric('opening_card')} s, "
          f"first scene verified at {first_scene} s, film ready at {timings['total_s']} s")
    return 0


def cmd_research(photo, place=None, lang="en", yes=False, no_cache=False, verify_with="baseten",
                 progress=None):
    cache = None if no_cache else Cache("out/cache")
    models.reset_usage()
    timings = {}
    start = time.perf_counter()
    try:
        phase = time.perf_counter()
        identify_steps = {}
        found = identify.identify(photo, place=place, respond=vision_respond, cache=cache,
                                  lang=lang, timings=identify_steps, progress=progress)
        timings["identify_s"] = round(time.perf_counter() - phase, 1)
        timings["identify_steps"] = identify_steps
        print(f"identify steps (s): {json.dumps(identify_steps)}")
    except identify.NotIdentifiedError as exc:
        print(f"identify steps (s): {json.dumps(identify_steps)}")
        print(f"object: not identified ({exc})")
        print("outcome: not_identified")
        return 2
    except identify.SourceError as exc:
        print(f"source failed: {exc}")
        return 2
    print(describe_found(found))
    if found.qid:
        print(f"wikidata: https://www.wikidata.org/wiki/{found.qid}")
    order = research.read_langs(found.country_code, lang)
    with ThreadPoolExecutor(max_workers=1) as pool:
        facts_future = (
            pool.submit(research.fetch_facts, found.qid, None, time.sleep, lang, cache,
                        found.country_code)
            if found.qid else None
        )
        if not yes:
            answer = input(f"Is this {found.name}? [Y/n] ").strip().lower()
            if answer not in ("", "y", "yes"):
                print("not confirmed; stopping")
                return 2
        phase = time.perf_counter()
        facts = facts_future.result() if facts_future else {"facts": []}
    if cache is not None and found.qid:
        slug = slug_for(found.name, found.qid, found.articles, prefer=order)
        reviewed = cache.get_reviewed(found.qid, lang)
        if reviewed is not None:
            out_path = Path("out") / slug / "research.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(reviewed, indent=2, ensure_ascii=False))
            result = reviewed.get("outcome", {})
            print(f"outcome: {result.get('outcome')} (reviewed research reused; use --no-cache to redo)")
            print(f"saved: {out_path}")
            return 0
        film = cached_film(slug)
        if film is not None:
            result = film.get("outcome", {})
            print(f"outcome: {result.get('outcome')} (cached film from {film.get('saved_at')}; "
                  f"use --no-cache to check again)")
            print(f"saved: {Path('out') / slug / 'research.json'}")
            return 0

    claims = []
    if found.qid:
        claims.extend(research.wikidata_claims(found.qid, facts))
        timings["facts_s"] = round(time.perf_counter() - phase, 1)
        print(f"wikidata facts: {len(facts['facts'])} statements, {len(claims)} dated claims")
    build_anchor_year = next((c["year"] for c in claims if c.get("anchor") == "build"), None)
    if build_anchor_year is not None:
        print(f"build anchor: {build_anchor_year} fixed by Wikidata")
    phase = time.perf_counter()
    question = research.lifespan_question(
        found.name, place or "", found.articles,
        read_langs=research.read_langs(found.country_code, lang),
    )
    answer = research.ask_lifespan(lifespan_respond, question)
    timings["research_s"] = round(time.perf_counter() - phase, 1)
    modelled = research.assemble_claims(answer["events"], answer["citations"], answer["sources"],
                                        anchor_year=build_anchor_year)
    if len(modelled) < len(answer["events"]):
        print(f"dropped (anchor stands): {len(answer['events']) - len(modelled)} research build years")
    claims.extend(modelled)
    print(f"lifespan events: {len(answer['events'])}")
    kept = keep_quality(claims)

    # Choose before checking: phase 1 verifies scene years, the build
    # and anchor claims and every state claim; spares verify only when
    # a scene needs a caption line.
    to_check, pool = plan_checks(kept)
    for c in pool:
        c.update({"verdict": "unverified", "quote": "", "url": None, "support": [],
                  "note": "outside chosen scenes", "completed": True,
                  "rewritten": None, "war_politics_only": False})
    print(f"checking {len(to_check)} of {len(kept)} claims (spares on need)")

    article_urls = [
        f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        for lang, title in found.articles.items()
    ]
    fetched = SourceTexts(cache=cache, progress=progress)
    texts = fetched.texts
    failures = fetched.failures
    anchor_year = min([c["year"] for c in kept], default=None)
    support = baseten_support_respond if verify_with == "baseten" else support_respond
    workers = models.VERIFY_OPEN.workers if verify_with == "baseten" else models.VERIFY.workers
    comparison = None

    def fetch_texts(claims):
        fetched.fetch(claims, article_urls, verify_with)

    def judge(claims):
        jobs = build_jobs(claims, texts, answer["snippets"], anchor_year)
        judged = verify.judge_all(support, jobs, search_respond=verify_respond,
                                  completion_respond=support_respond,
                                  max_workers=workers, progress=progress)
        apply_judged(claims, jobs, judged)
        fast = sum(1 for r in judged if r.get("fast_path"))
        if fast:
            print(f"fast paths: {fast} of {len(judged)} decided without a vote")
        return jobs, judged

    phase = time.perf_counter()
    fetch_texts(to_check)
    timings["fetch_s"] = round(time.perf_counter() - phase, 1)
    phase = time.perf_counter()
    jobs, judged = judge(to_check)
    timings["verify_s"] = round(time.perf_counter() - phase, 1)
    if verify_with == "both":
        phase = time.perf_counter()
        alt = verify.judge_all(baseten_support_respond, jobs, search_respond=verify_respond,
                               max_workers=models.VERIFY_OPEN.workers, completion=False)
        timings["verify_alt_s"] = round(time.perf_counter() - phase, 1)
        comparison = compare_verdicts(jobs, judged, alt)
        for job, other in zip(jobs, alt):
            claim = to_check[job["claim_index"]]
            claim["alt_verdict"] = other["verdict"]
            claim["alt_rounds"] = other.get("rounds", [])
        print(f"agreement: {comparison['agree']}/{comparison['total']} "
              f"(meta vs baseten support)")

    def refresh_film():
        film_verified = [c for c in kept if c["verdict"] == "supported"
                         or (c["verdict"] == "partly" and c["rewritten"])]
        film_timeline = research.build_timeline(timeline_events(film_verified))
        film_chosen = scenes.choose_scenes(film_timeline, film_verified)
        return film_verified, film_timeline, film_chosen

    verified, timeline, chosen = refresh_film()
    need = spare_needs(chosen, [c for c in pool if c["verdict"] == "unverified"])
    if need:
        spares = sorted([c for c in pool if c["verdict"] == "unverified"],
                        key=lambda c: states.classify(
                            c.get("event", "stood"), c.get("quote_span") or c["claim"])
                        is None)[:need]
        print(f"checking {len(spares)} spares for caption lines")
        phase = time.perf_counter()
        fetch_texts(spares)
        timings["fetch_s"] = round(timings["fetch_s"] + time.perf_counter() - phase, 1)
        phase = time.perf_counter()
        judge(spares)
        timings["verify_s"] = round(timings["verify_s"] + time.perf_counter() - phase, 1)
        verified, timeline, chosen = refresh_film()
    result = outcome.decide([{**c, "event": c.get("event", "stood")} for c in verified], identified=True)

    timings["total_s"] = round(time.perf_counter() - start, 1)
    report_and_save(found, lang, order, kept, timeline, chosen, result, timings,
                    verify_with, failures, comparison)
    return 0


def report_and_save(found, lang, order, kept, timeline, chosen, result, timings,
                    verify_with, failures, comparison, stream_events=None) -> str:
    """Print claims, scenes, timeline and outcome, then save research.json."""
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
        flagged = f" [FLAG: {s['flag']}]" if s.get("flag") else ""
        print(f"- {s.get('date_label', s['from_year'])}: {_show_state(s['state'])} ({s['reason']}){flagged}")
        for line in s["caption_lines"]:
            print(f"    line: {line['line'][:100]}")
    print("\ntimeline:")
    for seg in timeline:
        flagged = f" [FLAG: {seg['flag']}]" if seg.get("flag") else ""
        print(f"- {seg.get('date_label', seg['from_year'])} to {seg['to_year']}: "
              f"{_show_state(seg['state'])}{flagged}")
    print(f"\noutcome: {result['outcome']} ({result['reason']}; "
          f"{result['verified']} verified, {result['eras']} eras, {result['good_sources']} good sources)")

    slug = slug_for(found.name, found.qid, found.articles, prefer=order)
    out_dir = Path("out") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"timings (s): {json.dumps(timings)}")
    tokens = models.usage_totals()
    print(f"tokens: {json.dumps(tokens)}")
    saved = {
        "saved_at": date.today().isoformat(),
        "object": {"name": found.name, "kind": found.kind, "qid": found.qid, "articles": found.articles,
                   "lang": lang},
        "claims": kept,
        "timeline": timeline,
        "scenes": chosen,
        "outcome": result,
        "timings": timings,
        "tokens": tokens,
        "verify_with": verify_with,
        "failures": failures,
        "comparison": comparison,
    }
    if stream_events is not None:
        saved["stream"] = stream_events
    (out_dir / "research.json").write_text(json.dumps(saved, indent=2, ensure_ascii=False))
    print(f"saved: {out_dir / 'research.json'}")
    return slug


def _show_state(state: dict) -> str:
    shown = state["condition"]
    if state.get("scope", "whole") != "whole":
        shown += f" ({state['scope']})"
    if state.get("degree", "total") != "total":
        shown += f" ({state['degree']})"
    if state.get("description"):
        shown += f": {state['description'][:80]}"
    return shown


def keep_quality(claims) -> list:
    """Claims with at least one good source; weak-only claims are dropped."""
    kept = [c for c in claims if research.claim_quality_ok(c["sources"])]
    for c in claims:
        if not research.claim_quality_ok(c["sources"]):
            print(f"dropped (weak sources only): {c['year']} {c['claim'][:80]}")
    return kept


def draft_scenes(kept) -> list:
    """First-guess scenes from unverified claims; streaming verifies
    towards these, and the final choice re-runs on verified claims."""
    draft_events = [
        {"year": c["year"], "event": c.get("event", "stood"),
         "detail": c.get("quote_span") or c["claim"],
         "visible_change": c.get("visible_change", "")}
        for c in kept
    ]
    return scenes.choose_scenes(research.build_timeline(draft_events), kept)


def plan_checks(kept) -> tuple:
    """Phase 1 set: scene years, build and anchor claims, every state
    claim. Everything else waits in the spare pool."""
    draft = draft_scenes(kept)
    scene_years = {s["from_year"] for s in draft if isinstance(s["from_year"], int)}
    to_check = [c for c in kept if c["year"] in scene_years]
    if kept:  # the build and anchor claims are always verified, spares or not
        anchor_year = min(c["year"] for c in kept)
        for c in kept:
            if (c.get("event") or "").lower() in outcome.BUILD_WORDS or c["year"] == anchor_year:
                if c not in to_check:
                    to_check.append(c)
    for c in kept:  # every claim that could set a state
        detail = c.get("quote_span") or c["claim"]
        if states.classify(c.get("event", "stood"), detail) is not None and c not in to_check:
            to_check.append(c)
    pool = [c for c in kept if c not in to_check]
    return to_check, pool


def spare_needs(chosen, pool) -> int:
    """Spares verify only when a scene needs one: one per scene (other
    than today) without a caption line, capped."""
    needy = [s for s in chosen if s["from_year"] != "today" and not s["caption_lines"]]
    return min(len(needy), SPARES, len(pool))


def build_jobs(claims, texts, snippets, anchor_year) -> list:
    """Verify jobs: claim plus the paragraphs that mention its year or
    key words, best of three for the claims that matter. Jobs run in
    film order: the build anchor first, then earliest year first, so
    the first scene is ready first."""
    jobs = []
    for index, claim in enumerate(claims):
        keywords = verify.keywords_for_claim(claim["claim"], claim.get("event", ""))
        evidence = list(snippets)
        for url, text in texts.items():
            for para in verify.select_paragraphs(text, claim["year"], keywords, max_paras=3):
                evidence.append(f"{url}\n{para}")
        detail = claim.get("quote_span") or claim["claim"]
        jobs.append({
            "claim": claim["claim"], "event": claim.get("event", "stood"), "detail": detail,
            "year": claim["year"], "keywords": keywords, "passages": evidence[:13],
            "urls": claim["sources"], "votes": _votes_for(claim, detail, anchor_year),
            "anchor": claim.get("anchor"), "claim_index": index,
        })
    jobs.sort(key=lambda j: (j["anchor"] != "build", j["year"]))
    return jobs


class SourceTexts:
    """Fetched source texts with their attempts and failures, shared by
    batch research and the streaming film (used from one thread at a time)."""

    def __init__(self, cache=None, progress=None):
        self.texts: dict = {}
        self.attempted: set = set()
        self.failures: list = []
        self.cache = cache
        self.progress = progress

    def fetch(self, claims, article_urls, verify_with) -> None:
        urls = claim_urls(claims, article_urls, self.texts, self.attempted)
        self.attempted.update(urls)
        if not urls:
            return
        fetched, errors = verify.fetch_many(urls, cache=self.cache, progress=self.progress)
        self.texts.update(fetched)
        for url in sorted(errors):
            print(f"note: could not read {url} ({str(errors[url])[:100]})")
            self.failures.append({"url": url, "error": str(errors[url])[:200],
                                  "provider": verify_with})


def apply_judged(claims, jobs, judged) -> None:
    """Judged results back onto their claims, whatever order the jobs ran in."""
    for job, result in zip(jobs, judged):
        claim = claims[job["claim_index"]]
        claim.update(result)
        claim["war_politics_only"] = (
            claim["war_politics_only"] or bool(verify.flag_content(claim["claim"])))


def timeline_events(verified) -> list:
    """Verified claims become timeline events. A completed partly claim
    keeps its event: the rewrite narrows the wording, and context words
    in it never set the condition."""
    events = []
    for c in verified:
        if c["verdict"] == "partly" and c.get("rewritten"):
            detail = c["rewritten"]
        else:
            detail = c.get("quote_span") or c["claim"]
        events.append({"year": c["year"], "event": c.get("event", "stood"), "detail": detail,
                       "completed": c.get("completed", True), "verdict": "supported",
                       "visible_change": c.get("visible_change", ""),
                       "date_text": c.get("date_text", "")})
    return events


def _votes_for(claim, detail, anchor_year=None) -> int:
    """Best of three for the claims that matter: the build year, the
    anchor claim and every claim that would set a state."""
    if (claim.get("event") or "").lower() in outcome.BUILD_WORDS:
        return 3
    if anchor_year is not None and claim.get("year") == anchor_year:
        return 3
    if states.classify(claim.get("event", "stood"), detail) is not None:
        return 3
    return 1


FILM_CACHE_DAYS = 7


def cached_film(slug, max_age_days=FILM_CACHE_DAYS):
    """A second visit shows the same film: reuse this object's saved
    research when it is fresh. Refreshed after a week, or any time
    with --no-cache ("check again")."""
    path = Path("out") / slug / "research.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        saved = date.fromisoformat(data.get("saved_at", ""))
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if (date.today() - saved).days > max_age_days:
        return None
    return data


def describe_found(found) -> str:
    kind = getattr(found, "description", "") or found.kind
    lines = [f"object: {found.name} ({kind})"]
    for name in getattr(found, "rejected", ()):
        lines.append(f"note: second look rejected {name}; retried")
    return "\n".join(lines)


def claim_urls(claims, article_urls, fetched, attempted) -> list:
    """URLs still worth fetching: new, not already read, never failed before."""
    return sorted(
        {u for c in claims for u in c["sources"] if u not in fetched and u not in attempted}
        | {u for u in article_urls if u not in fetched and u not in attempted}
    )


def compare_verdicts(jobs, primary, alt, providers=("meta", "baseten")) -> dict:
    """Agreement between two providers judging identical jobs."""
    mine_key, alt_key = providers
    disagree = [
        {"claim": job["claim"][:120], mine_key: mine["verdict"], alt_key: other["verdict"]}
        for job, mine, other in zip(jobs, primary, alt)
        if mine["verdict"] != other["verdict"]
    ]
    return {"agree": len(jobs) - len(disagree), "total": len(jobs),
            "providers": list(providers), "disagree": disagree}


def slug_for(name, qid, articles, prefer=("en",)) -> str:
    """Filesystem slug in any script: transliterated name, else an article
    title in reading order, else the Wikidata id (e.g. q1196460-kintai-bridge)."""
    fallbacks = [lang for lang in ("en", "nl", "fr", "de") if lang not in prefer]
    candidates = [name, *(articles.get(lang, "") for lang in (*prefer, *fallbacks))]
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


def support_respond(prompt):
    resp = models.respond(
        _respond_for(models.VERIFY),
        models.VERIFY,
        input=prompt,
    )
    return json.loads(resp.model_dump_json())


def baseten_support_respond(prompt):
    try:
        resp = models.chat(
            _respond_for(models.VERIFY_OPEN),
            models.VERIFY_OPEN,
            messages=[{"role": "user", "content": prompt}],
            timeout=180,
        )
        return verify.text_answer(models.chat_answer(resp)["content"])
    except Exception as exc:  # noqa: BLE001 - demo insurance: meta judges instead
        print(f"note: baseten support failed ({str(exc)[:100]}), meta fallback",
              file=sys.stderr)
        return support_respond(prompt)


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
