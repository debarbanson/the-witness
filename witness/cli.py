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

from witness import captions, check, children, identify, layers, models, outcome, paint, research, scenes, states, stream, verify
from witness.cache import Cache
from witness.render import builder as render_builder


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
            cmd.add_argument("--paint", action="store_true")
    keep = sub.add_parser("keep")
    keep.add_argument("slug")
    child_cmd = sub.add_parser("children")
    child_cmd.add_argument("slug")
    caption_cmd = sub.add_parser("captions")
    caption_cmd.add_argument("slug")
    layers_cmd = sub.add_parser("layers")
    layers_cmd.add_argument("slug")
    layers_cmd.add_argument("--mode", default="parallel", choices=("chain", "parallel", "stream"))
    layers_cmd.add_argument("--tag", default=None)
    render_cmd = sub.add_parser("render")
    render_cmd.add_argument("slug")
    render_cmd.add_argument("--photo", required=True)
    render_cmd.add_argument("--subject", default=None)
    render_cmd.add_argument("--place", default="")
    render_cmd.add_argument("--era-dir", default="eras_parallel")
    render_cmd.add_argument("--layers-dir", default=None)
    render_cmd.add_argument("--photo-credit", default="")
    render_cmd.add_argument("--own-photo", action="store_true")
    render_cmd.add_argument("--mp4", action="store_true")
    paint_cmd = sub.add_parser("paint")
    paint_cmd.add_argument("slug")
    paint_cmd.add_argument("--photo", required=True)
    paint_cmd.add_argument("--place", required=True)
    paint_cmd.add_argument("--mode", default="parallel", choices=("chain", "parallel"))
    paint_cmd.add_argument("--scenes", default=None)
    paint_cmd.add_argument("--tag", default=None)
    args = parser.parse_args(argv)
    if args.command == "identify":
        return cmd_identify(args.photo, place=args.place, lang=args.lang,
                            yes=args.yes, no_cache=args.no_cache)
    if args.command == "keep":
        return cmd_keep(args.slug)
    if args.command == "children":
        return cmd_children(args.slug)
    if args.command == "captions":
        return cmd_captions(args.slug)
    if args.command == "layers":
        return cmd_layers(args.slug, mode=args.mode, tag=args.tag)
    if args.command == "render":
        from witness.render import record as render_record

        code = cmd_render(args.slug, args.photo, subject=args.subject, place=args.place,
                          era_dir=args.era_dir, layers_dir=args.layers_dir,
                          photo_credit=args.photo_credit,
                          own_photo=args.own_photo)
        if code == 0 and args.mp4:
            film_html = Path("out") / args.slug / "film" / "film.html"
            out_mp4 = Path("out") / args.slug / "film" / "film.mp4"
            print("recording MP4 (needs an unsandboxed browser)...")
            render_record.record(film_html, out_mp4)
            print(f"MP4 at {out_mp4}")
        return code
    if args.command == "paint":
        return cmd_paint(args.slug, args.photo, place=args.place,
                         mode=args.mode, scenes=args.scenes, tag=args.tag)
    if args.command == "film":
        return cmd_film(args.photo, place=args.place, lang=args.lang,
                        yes=args.yes, no_cache=args.no_cache,
                        verify_with=args.verify_with, paint_eras=args.paint)
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


def cli_progress(event, data):
    """Default CLI progress sink: source failures print as notes."""
    if event == "source_error":
        print(f"note: {data.get('source')} failed: {data.get('error')}")


def cmd_identify(photo, place=None, lang="en", yes=False, no_cache=False):
    cache = None if no_cache else Cache("out/cache")
    try:
        steps = {}
        found = identify.identify(photo, place=place, respond=vision_respond, cache=cache,
                                  lang=lang, timings=steps, progress=cli_progress)
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
             progress=None, paint_eras=False, paint_call=None, check_call=None):
    """The film as a stream: opening card within seconds, then one ready
    scene after another. Research starts while the user still confirms.
    With paint_eras, scene 1 paints from the anchor while research runs
    and later scenes paint as they verify."""
    filmed = stream.FilmStream()
    cache = None if no_cache else Cache("out/cache")
    models.reset_usage()
    timings = {}
    start = time.perf_counter()
    if progress is None:
        progress = cli_progress
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

    def gather_rest(first):
        claims = first["claims"]
        build_anchor_year = first["build_anchor_year"]
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

    def gather():
        return gather_rest(film_facts(found, lang, cache, timings))

    def show_card(claims):
        card = stream.opening_card(found.name, found.kind, claims, photo)
        filmed.emit("opening_card", card)
        print(f"\n---\n{card['name']} ({card['kind']})", flush=True)
        if card["text"]:
            print(card["text"])
        print("---", flush=True)

    paint_pool = None
    paint_futures = {}
    anchor_future = None
    paint_fn = paint_call or paint_respond
    check_fn = check_call or check_respond
    photo_bytes = Path(photo).read_bytes() if paint_eras else None
    era_dir = None
    if paint_eras:
        paint_pool = ThreadPoolExecutor(max_workers=6)
        era_dir = Path("out") / slug_for(found.name, found.qid, found.articles,
                                         prefer=order) / "eras_stream"
        era_dir.mkdir(parents=True, exist_ok=True)

    def verify_anchor_early(card_claims):
        """The build anchor checked against article text, before research."""
        anchor_claim = next((c for c in card_claims if c.get("anchor") == "build"), None)
        if anchor_claim is None:
            return None
        fetched.fetch([anchor_claim], article_urls, verify_with)
        job = build_jobs([anchor_claim], fetched.texts, [], anchor_claim["year"])[0]
        if job["anchor"] == "build" and job["passages"] and verify.anchor_hit(
                job["passages"], job["year"]):
            return anchor_claim["year"]
        return None

    def paint_scene_worker(scene, scene_no, with_photo):
        prev_id = anchor_future.result() if not with_photo else None
        result = paint.paint_scene(paint_fn, check_fn, scene, found.name, place or "",
                                   prev_id,
                                   photo_bytes=photo_bytes if with_photo else None)
        filmed.emit("scene_painted", {"scene": scene_no, "year": scene["from_year"],
                                      "verdict": result["verdict"],
                                      "attempts": result["attempts"]})
        if result["image"] is not None:
            (era_dir / f"{scene['from_year']}.png").write_bytes(result["image"])
            print(f"Scene {scene_no} ({scene.get('date_label', scene['from_year'])}) painted",
                  flush=True)
        else:
            print(f"Scene {scene_no} ({scene.get('date_label', scene['from_year'])}) "
                  f"dropped ({result['note']})", flush=True)
        return result

    def start_scene1(card_claims):
        """Scene 1 paints from the anchor while research runs; later
        scenes branch from its response id, or a plain anchor turn."""
        nonlocal anchor_future
        scene1_future = None
        anchor_year = verify_anchor_early(card_claims)
        if anchor_year is not None:
            print(f"scene 1 ({anchor_year}) verified from the anchor; "
                  f"painting while research runs", flush=True)
            scene1_future = paint_pool.submit(
                paint_scene_worker, film_anchor_scene(found.name, anchor_year),
                1, True)
            paint_futures[anchor_year] = scene1_future
        if scene1_future is not None:
            anchor_future = paint_pool.submit(
                lambda: (scene1_future.result()["response_id"]
                         or paint.paint_anchor(paint_fn, photo_bytes, found.name,
                                               place or "")["response_id"]))
        else:
            anchor_future = paint_pool.submit(
                paint.paint_anchor, paint_fn, photo_bytes, found.name, place or "")

    if yes:
        first = film_facts(found, lang, cache, timings)
        show_card(first["claims"])
        if paint_eras:
            start_scene1(first["claims"])
        gathered = gather_rest(first)
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
            if paint_pool is not None:
                paint_pool.shutdown(wait=False)
            return 2
        show_card(gathered["kept"])
        if paint_eras:
            start_scene1(gathered["kept"])

    def emit_scene(scene_no, scene):
        filmed.emit("scene_verified", {"scene": scene_no, "year": scene["from_year"],
                                       "date_label": scene.get("date_label")})
        print(f"Scene {scene_no} ({scene.get('date_label', scene['from_year'])}) verified",
              flush=True)

    phase = time.perf_counter()
    to_check, draft, jobs = gathered["to_check"], gathered["draft"], gathered["jobs"]
    judged_years: list = []
    emitted: set = set()
    to_check_years = [c["year"] for c in to_check]
    numbers = stream.scene_numbers(draft)
    for index, result in verify.judge_stream(support, jobs, search_respond=verify_respond,
                                             completion_respond=support,
                                             max_workers=workers, progress=progress,
                                             dispute_check=verify.sentence_disputed):
        claim = to_check[jobs[index]["claim_index"]]
        claim.update(result)
        claim["war_politics_only"] = (
            claim["war_politics_only"] or bool(verify.flag_content(claim["claim"])))
        judged_years.append(claim["year"])
        for scene in stream.newly_ready_scenes(draft, judged_years, to_check_years, emitted):
            emitted.add(scene["from_year"])
            emit_scene(numbers[scene["from_year"]], scene)
            if (paint_eras and isinstance(scene["from_year"], int)
                    and scene["from_year"] not in paint_futures):
                paint_futures[scene["from_year"]] = paint_pool.submit(
                    paint_scene_worker, scene, numbers[scene["from_year"]], False)
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
                                  progress=progress,
                                  dispute_check=verify.sentence_disputed)
        apply_judged(spares, spare_jobs, judged)
        timings["verify_s"] = round(timings["verify_s"] + time.perf_counter() - phase, 1)
        verified, timeline, chosen = refresh_film()
    if paint_eras:
        # The final choice can differ from the draft (failed claims move
        # scenes); chosen scenes never painted as drafts paint now, late
        # but complete, numbered in final film order.
        final_numbers = stream.scene_numbers(chosen)
        for scene in chosen:
            year = scene["from_year"]
            if isinstance(year, int) and year not in paint_futures:
                filmed.emit("scene_verified", {"scene": final_numbers[year],
                                               "year": year,
                                               "date_label": scene.get("date_label")})
                print(f"Scene {final_numbers[year]} ({scene.get('date_label', year)}) "
                      f"verified (final choice)", flush=True)
                paint_futures[year] = paint_pool.submit(
                    paint_scene_worker, scene, final_numbers[year], False)
    result = outcome.decide([{**c, "event": c.get("event", "stood")} for c in verified], identified=True)
    if paint_eras:
        entries = {}
        for year, future in paint_futures.items():
            outcome_result = future.result()
            entry = {"year": year, "verdict": outcome_result["verdict"],
                     "attempts": outcome_result["attempts"]}
            if outcome_result["image"] is not None:
                entry["file"] = f"eras_stream/{year}.png"
            else:
                entry["note"] = outcome_result["note"]
            entries[year] = entry
        paint_pool.shutdown()
        kept_files = sorted(era_dir.glob("[0-9]*.png"), key=lambda p: p.stem)
        if kept_files:
            paint.contact_sheet([(p.stem, p.read_bytes()) for p in kept_files],
                                str(era_dir / "contact.png"))
        (era_dir.parent / "paint_stream.json").write_text(json.dumps(
            {"mode": "stream", "object": found.name,
             "eras": [entries[y] for y in sorted(entries)]}, indent=1))
    timings["total_s"] = round(time.perf_counter() - start, 1)
    report_and_save(found, lang, order, gathered["kept"], timeline, chosen, result,
                    timings, verify_with, fetched.failures, None,
                    stream_events=filmed.events)
    first_scene = filmed.metric("scene_verified")
    line = (f"stream: opening card at {filmed.metric('opening_card')} s, "
            f"first scene verified at {first_scene} s, "
            f"film ready at {timings['total_s']} s")
    if paint_eras:
        painted_times = {e["year"]: e["t"] for e in filmed.events
                         if e["event"] == "scene_painted" and e["verdict"] == "matches"}
        ready = [(s["from_year"], painted_times[s["from_year"]])
                 for s in chosen if s["from_year"] in painted_times]
        ready.append(("today", 0.0))  # the user's photo needs no build
        playback = stream.simulate_playback(ready)
        pauses = ", ".join(str(y) for y in playback["pauses"]) or "none"
        line = (f"stream: opening card at {filmed.metric('opening_card')} s, "
                f"first scene verified at {first_scene} s, "
                f"first scene painted at {filmed.metric('scene_painted')} s, "
                f"film ready at {timings['total_s']} s, playback pauses: {pauses}")
    print(line)
    return 0


def cmd_research(photo, place=None, lang="en", yes=False, no_cache=False, verify_with="baseten",
                 progress=None):
    cache = None if no_cache else Cache("out/cache")
    models.reset_usage()
    timings = {}
    start = time.perf_counter()
    if progress is None:
        progress = cli_progress
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
                                  max_workers=workers, progress=progress,
                                  dispute_check=verify.sentence_disputed)
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
                               max_workers=models.VERIFY_OPEN.workers, completion=False,
                               dispute_check=verify.sentence_disputed)
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


def film_facts(found, lang, cache, timings) -> dict:
    """Wikidata facts and the build anchor: everything the opening card
    needs, before research starts."""
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
    return {"facts": facts, "claims": claims, "build_anchor_year": build_anchor_year}


def film_anchor_scene(object_name, anchor_year) -> dict:
    """Scene 1 from the anchor alone: the object as built, painted
    while research still runs."""
    return {"from_year": anchor_year, "date_label": str(anchor_year),
            "state": {"condition": "standing", "degree": "total",
                      "scope": "whole",
                      "description": f"newly completed in {anchor_year}, "
                                     f"standing whole and new"},
            "caption_lines": []}


def keep_quality(claims) -> list:
    """Claims with at least one good source; weak-only claims are dropped.

    The same claim twice is one claim: exact duplicates are dropped, so
    every kept claim lands in exactly one of the check lists downstream.
    """
    kept = []
    seen = set()
    for c in claims:
        if not research.claim_quality_ok(c["sources"]):
            print(f"dropped (weak sources only): {c['year']} {c['claim'][:80]}")
            continue
        key = json.dumps(c, sort_keys=True, default=str)
        if key in seen:
            print(f"dropped (duplicate claim): {c['year']} {c['claim'][:80]}")
            continue
        seen.add(key)
        kept.append(c)
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
        client = _respond_for(models.VERIFY_OPEN)
    except SystemExit:
        # _respond_for already named the missing key: meta judges instead.
        print("note: baseten unavailable, meta fallback", file=sys.stderr)
        return support_respond(prompt)
    try:
        resp = models.chat(
            client,
            models.VERIFY_OPEN,
            messages=[{"role": "user", "content": prompt}],
            timeout=180,
        )
        return verify.text_answer(models.chat_answer(resp)["content"])
    except Exception as exc:  # noqa: BLE001 - demo insurance: meta judges instead
        print(f"note: baseten support failed ({str(exc)[:100]}), meta fallback",
              file=sys.stderr)
        return support_respond(prompt)


def paint_respond(prompt, prev_id, photo_bytes=None):
    """One painting turn on Muse Image. Settings stay inside the tool."""
    from openai import BadRequestError

    content = [{"type": "input_text", "text": prompt}]
    if photo_bytes is not None:
        uri, _ = check.data_uri(photo_bytes)
        content.append({"type": "input_image", "image_url": uri})
    kwargs = {"tools": paint.image_tools(), "input": [
        {"role": "user", "content": content}]}
    if prev_id is not None:
        kwargs["previous_response_id"] = prev_id
    try:
        resp = models.respond(_respond_for(models.PAINT), models.PAINT, **kwargs)
    except BadRequestError as exc:
        if paint.is_safety_block(exc):
            raise paint.PaintSafetyError(str(exc))
        raise paint.PaintError(str(exc))
    data = json.loads(resp.model_dump_json())
    b64 = paint.extract_image_b64(data)
    if b64 is None:
        raise paint.PaintError("no image in the response")
    return {"image": base64.b64decode(b64), "response_id": data["id"]}


def check_respond(image_bytes, prompt):
    """One painting check on Muse Spark with vision."""
    uri, _ = check.data_uri(image_bytes)
    resp = models.respond(
        _respond_for(models.CHECK),
        models.CHECK,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": uri},
        ]}],
    )
    data = json.loads(resp.model_dump_json())
    texts = []
    for item in data.get("output", []):
        for block in item.get("content", []) or []:
            if block.get("type") == "output_text":
                texts.append(block.get("text", ""))
    return "\n".join(texts)


def recover_or_retry(call, checker, scene, name, place, photo_bytes,
                       directives, prior_dirs, dropped):
    """A dropped critical era first tries the newest kept painting of
    it from an earlier run; remains then get one calm aftermath try."""
    year = scene["from_year"]
    prior = []
    for run_dir in prior_dirs:
        candidate = run_dir / f"{year}.png"
        if candidate.exists():
            prior.append((str(candidate), candidate.read_bytes()))
    hit = paint.recover_scene(checker, scene, name, prior)
    if hit is not None:
        print(f"{year}: recovered from {hit['source']}")
        return {"year": year, "image": hit["image"], "response_id": None,
                "verdict": "recovered", "attempts": dropped["attempts"],
                "note": f"recovered from {hit['source']}: {hit['note']}"}
    condition = (scene.get("state") or {}).get("condition")
    if condition in paint.REMAINS_CONDITIONS:
        print(f"{year}: trying the aftermath")
        return paint.paint_aftermath(
            call, checker, scene, name, place, photo_bytes,
            season=directives["season"])
    return dropped


def cmd_paint(slug, photo, place=None, mode="parallel", scenes=None, tag=None,
              paint_call=None, check_call=None, photo_call=None):
    """Paint an object's eras from its research, checked per era."""
    out_dir = Path("out") / slug
    path = out_dir / "research.json"
    if not path.exists():
        print(f"no research at {path}")
        return 2
    data = json.loads(path.read_text())
    name = data["object"]["name"]
    photo_bytes = Path(photo).read_bytes()
    wanted = {int(y) for y in scenes.split(",")} if scenes else None
    eras = [s for s in data.get("scenes", [])
            if isinstance(s.get("from_year"), int)
            and not states.is_age_range(s.get("date_label", ""))
            and (wanted is None or s["from_year"] in wanted)]
    if not eras:
        print("no paintable eras in research")
        return 2
    call = paint_call or paint_respond
    checker = check_call or check_respond
    looker = photo_call or check_respond
    dated = [(s["from_year"],
              (s.get("state") or {}).get("description", "") + " " +
              " ".join(line.get("line", "") for line in s.get("caption_lines", [])))
             for s in data.get("scenes", []) if isinstance(s.get("from_year"), int)]
    directives = paint.paint_directives(looker, photo_bytes, dated)
    print(f"anchor season: {directives['season']}")
    if any(directives["excluded"].values()):
        print(f"anchor elements held back: "
              f"{sorted({el for els in directives['excluded'].values() for el in els})}")
    started = time.perf_counter()
    if mode == "chain":
        results = paint.paint_chain(call, photo_bytes, eras, name, place,
                                    check_call=checker, season=directives["season"],
                                    excluded=directives["excluded"],
                                    claims=data.get("claims", []))
    else:
        results = paint.paint_parallel(call, photo_bytes, eras, name, place,
                                       check_call=checker, season=directives["season"],
                                       excluded=directives["excluded"],
                                       claims=data.get("claims", []))
    suffix = f"{mode}_{tag}" if tag else mode
    era_dir = out_dir / f"eras_{suffix}"
    era_dir.mkdir(parents=True, exist_ok=True)
    prior_dirs = sorted(
        (d for d in out_dir.glob("eras_*") if d != era_dir and d.is_dir()),
        key=lambda d: d.stat().st_mtime, reverse=True)
    manifest_path = out_dir / f"paint_{suffix}.json"
    entries = {}
    if manifest_path.exists():
        for entry in json.loads(manifest_path.read_text()).get("eras", []):
            entries[entry["year"]] = entry
    for scene, result in zip(eras, results):
        year = scene["from_year"]
        if result["image"] is None:
            result = recover_or_retry(call, checker, scene, name, place,
                                      photo_bytes, directives, prior_dirs,
                                      result)
        entry = {"year": year, "verdict": result["verdict"],
                 "attempts": result["attempts"]}
        if result["image"] is not None:
            (era_dir / f"{year}.png").write_bytes(result["image"])
            entry["file"] = f"eras_{suffix}/{year}.png"
            if result["verdict"] == "recovered":
                entry["note"] = result["note"]
        else:
            entry["note"] = result["note"]
        entries[year] = entry
        print(f"{year}: {result['verdict']} "
              f"(attempts {result['attempts']}) {result.get('note', '')}"[:160])
    kept_files = sorted(era_dir.glob("[0-9]*.png"), key=lambda p: p.stem)
    if kept_files:
        paint.contact_sheet([(p.stem, p.read_bytes()) for p in kept_files],
                            str(era_dir / "contact.png"))
    manifest = {"slug": slug, "mode": mode, "object": name,
                "paint_s": round(time.perf_counter() - started, 1),
                "season": directives["season"],
                "eras": [entries[y] for y in sorted(entries)]}
    manifest_path.write_text(json.dumps(manifest, indent=1))
    kept = sum(1 for e in manifest["eras"] if e["verdict"] == "matches")
    print(f"painted {kept} of {len(eras)} eras in {manifest['paint_s']} s ({mode})")
    return 0


def child_rewrite_respond(adult, source, plain):
    """One children rewrite on Muse Spark, steady temperature."""
    prompt = children.rewrite_prompt(adult, source)
    if plain:
        prompt += " Use even plainer words."
    resp = models.respond(_respond_for(models.VERIFY), models.VERIFY, input=prompt)
    data = json.loads(resp.model_dump_json())
    texts = []
    for item in data.get("output", []):
        for block in item.get("content", []) or []:
            if block.get("type") == "output_text":
                texts.append(block.get("text", ""))
    return "\n".join(texts).strip()


def child_support_respond(line, source):
    """Re-verify a rewrite against its own source sentence."""
    job = {"claim": line, "event": "stood", "detail": line, "year": 0,
           "keywords": [], "passages": [source], "urls": [], "votes": 1}
    return verify.judge_claim(baseten_support_respond, job, completion=False)["verdict"]


def caption_rewrite_respond(detail, quote, year, plain):
    """One caption sentence on Muse Spark, steady temperature."""
    prompt = captions.sentence_prompt(detail, quote, year)
    if plain:
        prompt += " Shorter and simpler."
    resp = models.respond(_respond_for(models.VERIFY), models.VERIFY, input=prompt)
    data = json.loads(resp.model_dump_json())
    texts = []
    for item in data.get("output", []):
        for block in item.get("content", []) or []:
            if block.get("type") == "output_text":
                texts.append(block.get("text", ""))
    return "\n".join(texts).strip()


def caption_support_respond(sentence, quote):
    """Re-verify a caption sentence against its own source sentence."""
    job = {"claim": sentence, "event": "stood", "detail": sentence, "year": 0,
           "keywords": [], "passages": [quote], "urls": [], "votes": 3}
    return verify.judge_claim(baseten_support_respond, job, completion=False)["verdict"]


def cmd_captions(slug, rewrite_call=None, support_call=None):
    """Line-2 sentences from each scene's own verified claim."""
    out_dir = Path("out") / slug
    path = out_dir / "research.json"
    if not path.exists():
        print(f"no research at {path}")
        return 2
    data = json.loads(path.read_text())
    rewrite = rewrite_call or caption_rewrite_respond
    support = support_call or caption_support_respond
    assigned = captions.assign_claims(data.get("scenes", []),
                                      data.get("claims", []))
    failed = []
    for scene in data.get("scenes", []):
        year = scene.get("from_year")
        if not isinstance(year, int) or scene.get("caption_sentence"):
            continue
        if states.is_age_range(scene.get("date_label", "")):
            continue
        claim = assigned.get(year)
        if claim is None:
            scene["caption_sentence"] = {
                "text": captions.fallback_line(scene),
                "claim_year": None, "claim_url": None}
            print(f"{year}: fallback (no claim of its own)")
            continue
        out = captions.write_sentence(rewrite, support, claim, year)
        if not out["verified"]:
            failed.append(year)
            print(f"{year}: sentence failed verification")
            continue
        scene["caption_sentence"] = {"text": out["sentence"],
                                     "claim_year": year,
                                     "claim_url": claim.get("url")}
        print(f"{year}: {out['sentence']}"[:140])
    path.write_text(json.dumps(data, indent=1))
    if failed:
        print(f"caption sentences failed for {failed}; fix and rerun")
        return 1
    return 0


def cmd_children(slug, rewrite_call=None, support_call=None):
    """Children's captions next to the adult ones, re-verified or dropped."""
    out_dir = Path("out") / slug
    path = out_dir / "research.json"
    if not path.exists():
        print(f"no research at {path}")
        return 2
    data = json.loads(path.read_text())
    rewrite = rewrite_call or child_rewrite_respond
    support = support_call or child_support_respond
    verified = [c for c in data.get("claims", [])
                if c.get("verdict") in ("supported", "partly") and c.get("quote")]
    kept, dropped = 0, 0
    for scene in data.get("scenes", []):
        for entry in scene.get("caption_lines", []):
            claim = children.claim_for_line(verified, entry["year"], entry.get("url"))
            if claim is None:
                entry["child"], entry["child_verified"] = None, False
                dropped += 1
                continue
            out = children.child_caption(rewrite, support, entry["line"], claim["quote"])
            entry["child"], entry["child_verified"] = out["line"], out["verified"]
            kept, dropped = kept + out["verified"], dropped + (not out["verified"])
            print(f"{entry['year']}: {out['line'] or 'dropped'}"[:140])
        state_claim = next((c for c in verified if c["year"] == scene["from_year"]), None)
        description = (scene.get("state") or {}).get("description", "")
        if state_claim is not None and description:
            out = children.child_caption(rewrite, support, description,
                                         state_claim["quote"])
            scene["child_state"] = out["line"]
            print(f"{scene['from_year']} state: {out['line'] or 'dropped'}"[:140])
        else:
            scene["child_state"] = None
    path.write_text(json.dumps(data, indent=1))
    print(f"children captions: {kept} kept, {dropped} dropped")
    return 0


def sam_respond(text, jpeg_bytes):
    """One SAM request; returns the output text for the parser."""
    import base64

    uri = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
    client = _respond_for(models.SAM)
    resp = client.responses.create(
        model=models.SAM.model,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": text},
            {"type": "input_image", "image_url": uri},
        ]}],
    )
    data = json.loads(resp.model_dump_json())
    texts = []
    for item in data.get("output", []):
        for block in item.get("content", []) or []:
            if block.get("type") == "output_text":
                texts.append(block.get("text", ""))
    return "\n".join(texts)


def cmd_layers(slug, mode="parallel", tag=None, call_sam=None):
    """Figure layers for an object's painted eras (step 6)."""
    out_dir = Path("out") / slug
    suffix = f"{mode}_{tag}" if tag else mode
    era_dir = out_dir / f"eras_{suffix}"
    if not era_dir.exists():
        print(f"no painted eras at {era_dir}")
        return 2
    call = call_sam or sam_respond
    total = 0
    for path in sorted(era_dir.glob("[0-9]*.png"), key=lambda p: p.stem):
        found = layers.figures(call, str(path))
        layer_dir = out_dir / f"layers_{suffix}" / path.stem
        layer_dir.mkdir(parents=True, exist_ok=True)
        for i, layer in enumerate(found):
            layer["image"].save(layer_dir / f"figure_{i}.png")
        total += len(found)
        print(f"{path.stem}: {len(found)} figures")
    print(f"saved {total} figure layers under layers_{suffix}/")
    return 0


def cmd_render(slug, photo, subject=None, place="", era_dir="eras_parallel",
               layers_dir=None, photo_credit="", segment_call=None,
               own_photo=False):
    """Build the live film page from kept research plus paintings."""
    from witness import segment as segment_module

    out_dir = Path("out") / slug
    path = out_dir / "research.json"
    if not path.exists():
        print(f"no research at {path}")
        return 2
    data = json.loads(path.read_text())
    era_path = out_dir / era_dir
    era_files = {p.stem: str(p) for p in sorted(era_path.glob("[0-9]*.png"))}
    if not era_files:
        print(f"no painted eras at {era_path}")
        return 2
    images = {key: f"era_{key}.png" for key in era_files}
    layer_files = {}
    if layers_dir is not None and (out_dir / layers_dir).exists():
        for year_dir in sorted((out_dir / layers_dir).iterdir()):
            found = sorted(year_dir.glob("figure_*.png"))
            if found:
                layer_files[year_dir.name] = [str(p) for p in found]
    layers = {key: [f"layers_{key}/figure_{i}.png" for i in range(len(files))]
              for key, files in layer_files.items()}
    cutout_path = None
    if subject:
        seg = segment_call if segment_call is not None else segment_module.segment
        first = None if segment_call is not None else sam_respond
        cut = seg(first, photo, subject)
        cutout_path = out_dir / "today_cutout.png"
        cut.image.save(cutout_path)
    photo_dest = Path(photo).suffix or ".jpg"
    film_dir = render_builder.write_film(
        out_dir, data, images, f"today{photo_dest}", photo_credit, layers,
        place=place, era_files=era_files, layer_files=layer_files,
        photo_file=photo, cutout_file=str(cutout_path) if cutout_path else None,
        photo_year=identify.capture_year(photo), own_photo=own_photo)
    film = json.loads((film_dir / "film.json").read_text())
    total = film["segments"][-1]["end"]
    print(f"film at {film_dir}/film.html ({len(film['scenes'])} scenes, {total} s)")
    return 0


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
