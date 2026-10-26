"""Cross-run disk cache for free-source answers, keyed by URL and date.

Only public knowledge is cached (Wikidata answers, fetched source texts),
never the visitor's photo or location. Entries expire overnight.
"""

import hashlib
import json
from datetime import date
from pathlib import Path


class Cache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str):
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if payload.get("date") != date.today().isoformat() or "value" not in payload:
            return None
        return payload["value"]

    def put(self, key: str, value) -> None:
        self._path(key).write_text(
            json.dumps({"date": date.today().isoformat(), "url": key, "value": value})
        )

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode()).hexdigest()
        return self.root / f"{digest}.json"
