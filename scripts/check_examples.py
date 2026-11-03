"""After every example upload: the live films must equal the local ones.

Usage: python scripts/check_examples.py <base-url>

For each example, the live documentary and picture-book film.json must
equal out/<slug>/film/film.json byte for byte in meaning, and the
live evidence page must answer. Prints one line per example and exits
1 on any mismatch, so a stale upload fails loudly instead of reaching
judges. Run it after every upload and every deploy.
"""

import json
import sys
import urllib.request
from pathlib import Path

EXAMPLES = (
    ("de-adriaan", "out/q2763574-de-adriaan"),
    ("major-oak", "out/q388443-major-oak"),
    ("rubjerg-knude", "out/q2206180-rubjerg-knude-fyr"),
)


def compare(local, live) -> list:
    """Pinpointing differences between two film payloads; empty when
    the live film is the local one."""
    if local == live:
        return []
    problems = []
    for key in ("sibling_page", "today_line", "today_sub"):
        if local.get(key) != live.get(key):
            problems.append(
                f"{key}: local {local.get(key)!r} live {live.get(key)!r}")
    local_scenes = {scene.get("year"): scene
                    for scene in local.get("scenes", [])}
    live_scenes = {scene.get("year"): scene
                   for scene in live.get("scenes", [])}
    for year in sorted(set(local_scenes) | set(live_scenes), key=str):
        old, new = local_scenes.get(year), live_scenes.get(year)
        if old is None:
            problems.append(f"scene {year}: live-only")
        elif new is None:
            problems.append(f"scene {year}: missing live")
        elif old != new:
            problems.append(f"scene {year}: local {old!r} live {new!r}")
    only = sorted(set(local) ^ set(live), key=str)
    if only:
        problems.append(f"keys differ: {only}")
    return problems or ["payloads differ"]


def _read(url) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def check(base_url, root=".") -> list:
    """Every live example against the local films. Returns one problem
    string per mismatch; empty means the judge page serves exactly
    what is built here."""
    root = Path(root)
    problems = []
    for slug, local_dir in EXAMPLES:
        for name, path in (("film", "film.json"),
                           ("picture-book", "child/film.json")):
            local = json.loads(
                (root / local_dir / "film" / path).read_text())
            try:
                live = json.loads(
                    _read(f"{base_url}/examples/{slug}/{path}"))
            except Exception as exc:
                problems.append(f"{slug} {name}: unreachable ({exc})")
                continue
            problems.extend(f"{slug} {name}: {found}"
                            for found in compare(local, live))
        try:
            _read(f"{base_url}/examples/{slug}/evidence.html")
        except Exception as exc:
            problems.append(f"{slug} evidence: unreachable ({exc})")
    return problems


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: python scripts/check_examples.py <base-url>")
        return 2
    problems = check(argv[1])
    by_slug = {}
    for problem in problems:
        by_slug.setdefault(problem.split(" ", 1)[0], []).append(problem)
    failed = False
    for slug, _ in EXAMPLES:
        if slug in by_slug:
            failed = True
            for problem in by_slug[slug]:
                print(f"STALE {problem}")
        else:
            print(f"OK {slug}: live films equal the local ones")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
