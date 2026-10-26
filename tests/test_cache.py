"""Cross-run disk cache for free-source answers, keyed by URL and date."""

import json
from datetime import date, timedelta

from witness.cache import Cache


def test_roundtrip(tmp_path):
    cache = Cache(tmp_path)
    assert cache.get("https://example.com/x") is None
    cache.put("https://example.com/x", {"a": 1})
    assert cache.get("https://example.com/x") == {"a": 1}


def test_yesterdays_entry_is_stale(tmp_path):
    cache = Cache(tmp_path)
    cache.put("https://example.com/x", {"a": 1})
    for file in tmp_path.iterdir():
        payload = json.loads(file.read_text())
        payload["date"] = (date.today() - timedelta(days=1)).isoformat()
        file.write_text(json.dumps(payload))
    assert cache.get("https://example.com/x") is None


def test_params_join_the_key(tmp_path):
    cache = Cache(tmp_path)
    cache.put("https://example.com/x?a=1", {"a": 1})
    assert cache.get("https://example.com/x?a=2") is None
    assert cache.get("https://example.com/x?a=1") == {"a": 1}


def test_mediawiki_get_reads_and_writes_cache(tmp_path):
    from witness.web import mediawiki_get

    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"echo": True}}

    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return FakeResponse()

    cache = Cache(tmp_path)
    params = {"action": "query", "format": "json"}
    assert mediawiki_get(get, "https://example.com/w/api.php", params, cache=cache) == {"query": {"echo": True}}
    assert mediawiki_get(get, "https://example.com/w/api.php", params, cache=cache) == {"query": {"echo": True}}
    assert len(calls) == 1
