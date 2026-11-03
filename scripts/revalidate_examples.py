"""Revalidate the retained example eras through today's checks.

Report mode (default) runs the current caption check and the current
painting/state vision check on every stored artefact and saves the
record to eval/example_revalidation_2026-11-04.json, without touching
the manifests. With --write, a passing era also gets its binding
stamped, any earlier failure note cleared and its stored caption
refreshed; a failing era keeps no binding. Each check runs once; when
it fails it runs twice more, and every verdict is recorded. Never
retry until it passes, and never write a hash without running the
check. About $0.30.
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


def main(argv) -> int:
    write = "--write" in argv
    tmp = tempfile.mkdtemp()
    models.configure_spending(tmp, daily_cap_usd=CAP_USD)
    cache = Cache("out/cache")
    records = []
    failures = []
    try:
        for slug in SLUGS:
            slug_dir = Path("out") / slug
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
                    paint_verdicts = run_tries(lambda: check_painting(
                        slug_dir, entry, scene, name, season, audience))
                    seconds = round(time.perf_counter() - started, 1)
                    cost = round(models.current_cost_usd() - cost_before, 4)
                    cap_ok = caption_verdicts[-1]["ok"]
                    paint_ok = paint_verdicts[-1]["ok"]
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
    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text(json.dumps(
        {"date": "2026-11-04", "records": records}, indent=1))
    kept = sum(1 for row in records
               if row["caption_verdicts"][-1]["ok"]
               and row["paint_verdicts"][-1]["ok"])
    print(f"kept {kept}/{len(records)}, record at {RECORD_PATH}")
    if failures:
        print("FAILED:", ", ".join(f"{s} {y} {a}"
                                   for s, y, a in failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
