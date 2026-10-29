"""Cross-run disk cache for free-source answers, keyed by URL and date.

Only public knowledge is cached (Wikidata answers, fetched source texts),
never the visitor's photo or location. Entries expire overnight.
"""

import hashlib
import json
from datetime import date
from pathlib import Path


REVIEWED_KEYS = ("object", "claims", "timeline", "scenes", "outcome",
                 "source_note")


def reviewed_knowledge(data: dict) -> dict:
    """Knowledge a later visitor may reuse: no run totals, no photos."""
    return {key: data[key] for key in REVIEWED_KEYS if key in data}


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

    def put_reviewed(self, qid: str, lang: str, data: dict) -> None:
        """Owner-reviewed research for an object: knowledge only, never
        expires. Run totals and anything visitor-specific stay out."""
        path = self._reviewed_path(qid, lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reviewed_knowledge(data), ensure_ascii=False))

    def get_reviewed(self, qid: str, lang: str):
        path = self._reviewed_path(qid, lang)
        if not path.exists():
            return None
        try:
            return reviewed_knowledge(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return None

    def _reviewed_path(self, qid: str, lang: str) -> Path:
        safe = "".join(c if c.isalnum() else "-" for c in f"{qid}-{lang}")
        return self.root / "reviewed" / f"{safe}.json"
