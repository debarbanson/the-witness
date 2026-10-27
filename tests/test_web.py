"""Free-source plumbing: retries with backoff. No live calls."""

import pytest

from witness.web import WebError, mediawiki_get


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeHTTPError(self.status_code)


class FakeHTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = type("Resp", (), {"status_code": status})()


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, payload = entry
        return FakeResponse(status, payload)


def test_mediawiki_get_returns_first_success():
    get = FakeTransport([(200, {"query": {"ok": True}})])
    assert mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"}) == {
        "query": {"ok": True}}


def test_mediawiki_get_retries_transport_errors_with_backoff():
    get = FakeTransport(
        [TimeoutError("t1"), TimeoutError("t2"), (200, {"query": {"ok": True}})])
    sleeps = []
    data = mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                         sleep=sleeps.append)
    assert data == {"query": {"ok": True}}
    assert len(get.calls) == 3
    assert sleeps == [2, 4]


def test_mediawiki_get_retries_ratelimit_and_server_errors():
    get = FakeTransport(
        [(429, {}), (503, {}), (200, {"query": {"ok": True}})])
    sleeps = []
    data = mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                         sleep=sleeps.append)
    assert data == {"query": {"ok": True}}
    assert sleeps == [2, 4]


def test_mediawiki_get_does_not_retry_client_errors():
    get = FakeTransport([(404, {}), (200, {"query": {"ok": True}})])
    with pytest.raises(WebError):
        mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                      sleep=lambda s: None)
    assert len(get.calls) == 1


def test_mediawiki_get_gives_up_after_three_tries():
    get = FakeTransport([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")])
    with pytest.raises(WebError):
        mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                      sleep=lambda s: None)
    assert len(get.calls) == 3


def test_mediawiki_get_honours_fewer_tries():
    get = FakeTransport([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")])
    with pytest.raises(WebError):
        mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                      sleep=lambda s: None, tries=2)
    assert len(get.calls) == 2


def test_mediawiki_get_still_backs_off_on_maxlag():
    get = FakeTransport(
        [(200, {"error": {"code": "maxlag", "info": "lagged"}},),
         (200, {"query": {"ok": True}})])
    sleeps = []
    data = mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                         sleep=sleeps.append)
    assert data == {"query": {"ok": True}}
    assert sleeps == [5]


def test_mediawiki_get_retries_search_busy_then_succeeds():
    get = FakeTransport(
        [(200, {"error": {"code": "cirrussearch-too-busy-error",
                          "info": "Search is currently too busy. Please try again later."}}),
         (200, {"query": {"ok": True}})])
    sleeps = []
    data = mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                         sleep=sleeps.append)
    assert data == {"query": {"ok": True}}
    assert sleeps == [5]


def test_mediawiki_get_busy_on_every_try_raises():
    busy = (200, {"error": {"code": "cirrussearch-too-busy-error", "info": "busy"}})
    get = FakeTransport([busy, busy, busy])
    with pytest.raises(WebError):
        mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                      sleep=lambda s: None)
    assert len(get.calls) == 3


def test_mediawiki_get_still_raises_other_api_errors_at_once():
    get = FakeTransport(
        [(200, {"error": {"code": "badparam", "info": "bad"}}),
         (200, {"query": {"ok": True}})])
    with pytest.raises(WebError):
        mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"},
                      sleep=lambda s: None)
    assert len(get.calls) == 1


def test_mediawiki_get_bounds_default_timeout():
    get = FakeTransport([(200, {"query": {"ok": True}})])
    mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"})
    assert get.calls[0]["timeout"] == 15


def test_mediawiki_get_honours_explicit_timeout():
    get = FakeTransport([(200, {"query": {"ok": True}})])
    mediawiki_get(get, "https://example.com/w/api.php", {"a": "b"}, timeout=4)
    assert get.calls[0]["timeout"] == 4
