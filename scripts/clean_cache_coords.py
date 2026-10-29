"""Delete pre-A2 cache entries whose keys carry coordinates.

Only files whose stored lookup key contains a coordinate marker are
removed (Overpass and geosearch lookups from before coordinate caching
went memory-only). Reviewed research and all other entries are kept.
Prints the number of files removed, nothing else.

Usage: python scripts/clean_cache_coords.py [cache-dir]
"""

import json
import sys
from pathlib import Path

COORD_MARKERS = ("gscoord", "ggscoord", "overpass:")


def main(root="out/cache") -> int:
    removed = 0
    for path in sorted(Path(root).glob("*.json")):
        try:
            url = json.loads(path.read_text()).get("url", "")
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if isinstance(url, str) and any(m in url for m in COORD_MARKERS):
            path.unlink()
            removed += 1
    print(removed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/cache"))
