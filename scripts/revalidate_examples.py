"""Revalidate the retained example eras through today's checks.

Release rule for paintings: pass on the first check, or after a
failure two passes out of three on the same image hash. Never stop at
the first pass after a failure. (Reviewed state d972ddf; the rule
answers round-7 B1.) Captions keep their own strict check: every
caption verdict is recorded and the last one decides.

Report mode (default) runs the current caption check and the current
painting/state vision check on every stored artefact and saves the
record to eval/example_revalidation_2026-11-04.json, without touching
the manifests. With --write, a passing era also gets its binding
stamped, any earlier failure note cleared and its stored caption
refreshed; a failing era keeps no binding. --third SLUG,YEAR,AUDIENCE
runs one more paint check on the recorded bytes and appends it.
--sync stamps the manifests from the record without running any
check. Never retry until it passes, and never write a hash without
running the check. A full run is about $0.30.
"""

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")

from witness import captions, check as check_module, children, cli, models, paint
from witness.cache import Cache

SLUGS = ("q2763574-de-adriaan", "q388443-major-oak",
         "q2206180-rubjerg-knude-fyr")
RECORD_PATH = Path("eval/example_revalidation_2026-11-04.json")
CAP_USD = 5.0
REVIEWED_SHA = "d972ddf"
RULE = ("paintings: pass on the first check, or after a failure two "
        "passes out of three on the same image hash; never stop at "
        "the first pass after a failure")


def refresh_entry(entry, scene, name, audience, cap_ok, paint_ok,
                  paint_note) -> None:
    """Stamp or drop one manifest entry after today's checks. A pass
    sets the binding and verdict, clears any earlier failure note and
    refreshes the stored caption to the current one; a fail drops the
    binding and records the verdicts."""
    if cap_ok and paint_ok:
        entry["binding"] = paint.painting_binding(
            scene.get("state"),
            paint.scene_caption(scene, audience=audience),
            (scene.get("caption_sentence") or {}).get("evidence"))
        entry["verdict"] = "matches"
        entry.pop("note", None)
        entry["caption"] = paint.scene_caption(scene, audience=audience)
    else:
        entry["verdict"] = "dropped"
        entry["note"] = (f"revalidation: caption={cap_ok} "
                         f"paint={paint_ok}")
        entry.pop("binding", None)


def era_record(slug, year, audience, image_bytes, scene, caption_verdicts,
               paint_verdicts, seconds, cost_usd) -> dict:
    """One JSON-serializable record row. No coordinates, no places."""
    evidence = (scene.get("caption_sentence") or {}).get("evidence") or {}
    return {"slug": slug, "year": year, "audience": audience,
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "caption": paint.scene_caption(scene, audience=audience),
            "state": scene.get("state"),
            "quote": evidence.get("quote", ""),
            "url": evidence.get("url", ""),
            "caption_verdicts": caption_verdicts,
            "paint_verdicts": paint_verdicts,
            "seconds": seconds, "cost_usd": cost_usd}


def check_caption(scene, claim, claims, name, texts, audience):
    """Today's caption check on the stored sentence. Returns
    (verified, note). Pure besides the injected support calls."""
    stored = scene.get("caption_sentence") or {}
    if audience == "child":
        line = (stored.get("child") or {}).get("text", "")
        if not line:
            return False, "no stored child line"
        quote = (stored.get("evidence") or {}).get("quote", "")
        url = (stored.get("evidence") or {}).get("url", "")
        gentle = (scene.get("state") or {}).get("condition") in (
            children.GENTLE_CONDITIONS)
        out = children.child_caption(
            lambda *a: line, cli.child_support_respond,
            stored.get("text", ""), quote, url, gentle=gentle,
            year=scene.get("from_year", 0), object_name=name,
            texts=texts, stamp=scene.get("date_label", "") or "")
        return out["verified"], out.get("line", "")
    sentence = stored.get("text", "")
    if not sentence:
        return False, "no stored sentence"
    out = captions.write_sentence(
        lambda *a: sentence, cli.caption_support_respond, claim,
        scene.get("from_year", 0), claims=claims,
        stamp=scene.get("date_label", "") or "", object_name=name,
        texts=texts)
    return out["verified"], out.get("sentence", "")


def check_painting(slug_dir, entry, scene, name, season, audience):
    """Today's painting check on the stored image. Returns
    (matches, note)."""
    rel = entry.get("file")
    img_path = Path(slug_dir) / rel if rel else None
    if img_path is None or not img_path.exists():
        return False, f"missing file {rel}"
    caption = paint.scene_caption(scene, audience=audience)
    result = check_module.check_painting(
        cli.check_respond, img_path.read_bytes(), name,
        paint.describe_state(name, scene.get("state", {})),
        scene.get("from_year"), caption=caption, season=season,
        surroundings=paint.scene_context(scene))
    return result["verdict"] == "matches", result.get("note", "")[:200]


def run_tries(run):
    """Run once; on failure run twice more. Returns every verdict."""
    verdicts = []
    for _ in range(3):
        ok, note = run()
        verdicts.append({"ok": ok, "note": note})
        if ok:
            break
    return verdicts


def run_paint_tries(run):
    """One check; a first pass stops, a first failure always runs
    twice more on the same bytes. Returns every verdict."""
    verdicts = []
    ok, note = run()
    verdicts.append({"ok": ok, "note": note})
    if ok:
        return verdicts
    for _ in range(2):
        ok, note = run()
        verdicts.append({"ok": ok, "note": note})
    return verdicts


def paint_kept(verdicts) -> bool:
    """First pass, or two passes out of three after a failure."""
    if not verdicts:
        return False
    if verdicts[0]["ok"]:
        return True
    return sum(1 for verdict in verdicts if verdict["ok"]) >= 2


def _third_arg(argv) -> str | None:
    for index, arg in enumerate(argv):
        if arg == "--third" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _row_for(records, slug, year, audience) -> dict | None:
    for row in records:
        if (row.get("slug"), row.get("year"),
                row.get("audience")) == (slug, year, audience):
            return row
    return None


def _entry_for(manifest, year) -> dict | None:
    for entry in manifest.get("eras", []):
        if entry.get("year") == year:
            return entry
    return None


def _with_metadata(saved) -> dict:
    saved["rule"] = RULE
    saved["reviewed_sha"] = REVIEWED_SHA
    return saved


def third_check(root, record_path, spec) -> int:
    """Append one paint verdict to a recorded row, on the recorded
    bytes only. Returns 0 kept, 1 dropped, 2 refused."""
    try:
        slug, year_text, audience = spec.split(",")
        year = int(year_text)
    except ValueError:
        print(f"bad --third spec {spec!r}; want SLUG,YEAR,AUDIENCE")
        return 2
    saved = json.loads(Path(record_path).read_text())
    row = _row_for(saved.get("records", []), slug, year, audience)
    if row is None:
        print(f"no record row for {spec}")
        return 2
    slug_dir = Path(root) / slug
    suffix = "_child" if audience == "child" else ""
    manifest = json.loads(
        (slug_dir / f"paint_parallel_strict{suffix}.json").read_text())
    entry = _entry_for(manifest, year)
    data = json.loads((slug_dir / "research.json").read_text())
    scene = next((s for s in data.get("scenes", [])
                  if s.get("from_year") == year), None)
    if entry is None or scene is None:
        print(f"no manifest entry or scene for {spec}")
        return 2
    rel = entry.get("file")
    img_path = slug_dir / rel if rel else None
    digest = (hashlib.sha256(img_path.read_bytes()).hexdigest()
              if img_path is not None and img_path.exists() else "")
    if digest != row.get("sha256"):
        print(f"image bytes moved for {spec}; refusing the third check")
        return 2
    tmp = tempfile.mkdtemp()
    models.configure_spending(tmp, daily_cap_usd=CAP_USD)
    try:
        ok, note = check_painting(
            slug_dir, entry, scene, data["object"]["name"],
            manifest.get("season"), audience)
    finally:
        models.configure_spending(None)
    row["paint_verdicts"].append({"ok": ok, "note": note})
    cap_ok = row["caption_verdicts"][-1]["ok"]
    kept = cap_ok and paint_kept(row["paint_verdicts"])
    print(f"{spec}: paint={[v['ok'] for v in row['paint_verdicts']]} "
          f"-> {'KEEP' if kept else 'DROP'}")
    Path(record_path).write_text(
        json.dumps(_with_metadata(saved), indent=1))
    return 0 if kept else 1


def sync_manifests(root, record_path) -> int:
    """Stamp the manifests from the record's verdicts. No checks run;
    rows the record never saw are left alone."""
    saved = json.loads(Path(record_path).read_text())
    rows = {(row.get("slug"), row.get("year"), row.get("audience")): row
            for row in saved.get("records", [])}
    for slug in sorted({row.get("slug") for row in saved.get("records", [])}):
        slug_dir = Path(root) / slug
        if not (slug_dir / "research.json").exists():
            continue
        data = json.loads((slug_dir / "research.json").read_text())
        name = data["object"]["name"]
        scenes = {s.get("from_year"): s for s in data.get("scenes", [])
                  if isinstance(s.get("from_year"), int)}
        for suffix, audience in (("", "adult"), ("_child", "child")):
            manifest_path = (
                slug_dir / f"paint_parallel_strict{suffix}.json")
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text())
            changed = False
            for entry in manifest.get("eras", []):
                row = rows.get((slug, entry.get("year"), audience))
                if row is None:
                    continue
                cap_ok = row["caption_verdicts"][-1]["ok"]
                paint_ok = paint_kept(row["paint_verdicts"])
                refresh_entry(entry, scenes.get(entry.get("year"), {}),
                              name, audience, cap_ok, paint_ok,
                              row["paint_verdicts"][-1]["note"])
                changed = True
            if changed:
                manifest_path.write_text(json.dumps(manifest, indent=1))
                print(f"{slug} {audience or 'adult'}: manifests synced")
    Path(record_path).write_text(
        json.dumps(_with_metadata(saved), indent=1))
    return 0


def main(argv, root=Path("out"), record_path=RECORD_PATH) -> int:
    third = _third_arg(argv)
    if third is not None:
        return third_check(root, record_path, third)
    if "--sync" in argv:
        return sync_manifests(root, record_path)
    write = "--write" in argv
    tmp = tempfile.mkdtemp()
    models.configure_spending(tmp, daily_cap_usd=CAP_USD)
    cache = Cache("out/cache")
    records = []
    failures = []
    try:
        for slug in SLUGS:
            slug_dir = Path(root) / slug
            data = json.loads((slug_dir / "research.json").read_text())
            name = data["object"]["name"]
            scenes = {s.get("from_year"): s for s in data.get("scenes", [])
                      if isinstance(s.get("from_year"), int)}
            assigned = captions.assign_claims(data.get("scenes", []),
                                              data.get("claims", []))
            texts = cli.caption_texts(data, cache)
            for suffix, audience in (("", "adult"), ("_child", "child")):
                manifest_path = (
                    slug_dir / f"paint_parallel_strict{suffix}.json")
                manifest = json.loads(manifest_path.read_text())
                season = manifest.get("season")
                changed = False
                for entry in manifest.get("eras", []):
                    year = entry.get("year")
                    scene = scenes.get(year)
                    if scene is None:
                        print(f"{slug} {year} {audience}: no scene; skip",
                              flush=True)
                        continue
                    claim = assigned.get(year)
                    cost_before = models.current_cost_usd()
                    started = time.perf_counter()
                    caption_verdicts = run_tries(lambda: check_caption(
                        scene, claim, data.get("claims", []), name,
                        texts, audience))
                    paint_verdicts = run_paint_tries(
                        lambda: check_painting(
                            slug_dir, entry, scene, name, season,
                            audience))
                    seconds = round(time.perf_counter() - started, 1)
                    cost = round(models.current_cost_usd() - cost_before, 4)
                    cap_ok = caption_verdicts[-1]["ok"]
                    paint_ok = paint_kept(paint_verdicts)
                    status = "KEEP" if (cap_ok and paint_ok) else "DROP"
                    print(f"{slug} {year} {audience}: "
                          f"caption={[v['ok'] for v in caption_verdicts]} "
                          f"paint={[v['ok'] for v in paint_verdicts]} "
                          f"-> {status} ({seconds}s ${cost:.4f})",
                          flush=True)
                    rel = entry.get("file")
                    img_path = Path(slug_dir) / rel if rel else None
                    image = (img_path.read_bytes()
                             if img_path is not None and img_path.exists()
                             else b"")
                    records.append(era_record(
                        slug, year, audience, image, scene,
                        caption_verdicts, paint_verdicts, seconds, cost))
                    if not (cap_ok and paint_ok):
                        failures.append((slug, year, audience))
                    if write:
                        refresh_entry(entry, scene, name, audience,
                                      cap_ok, paint_ok,
                                      paint_verdicts[-1]["note"])
                        changed = True
                if write and changed:
                    manifest_path.write_text(json.dumps(manifest, indent=1))
    finally:
        models.configure_spending(None)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(
        _with_metadata({"date": "2026-11-04", "records": records}),
        indent=1))
    kept = sum(1 for row in records
               if row["caption_verdicts"][-1]["ok"]
               and paint_kept(row["paint_verdicts"]))
    print(f"kept {kept}/{len(records)}, record at {RECORD_PATH}")
    if failures:
        print("FAILED:", ", ".join(f"{s} {y} {a}"
                                   for s, y, a in failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
