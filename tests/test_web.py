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


def test_assert_public_url_blocks_non_public_hosts():
    from witness.web import assert_public_url

    for bad in ("http://127.0.0.1/", "http://10.1.2.3/x", "http://192.168.0.1/",
                "http://169.254.169.254/latest/meta-data", "http://[::1]/",
                "http://[fd00::1]/", "file:///etc/passwd", "gopher://x/"):
        with pytest.raises(WebError):
            assert_public_url(bad)


def test_assert_public_url_allows_public_and_unresolvable():
    from witness.web import assert_public_url

    assert_public_url("https://en.wikipedia.org/wiki/X")
    assert_public_url("https://no-such-host-12345.invalid/")


def test_assert_public_url_rejects_mixed_dns(monkeypatch):
    import socket
    from witness.web import assert_public_url

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [
        (2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(WebError):
        assert_public_url("https://example.org/")


def test_assert_public_url_rejects_nat64_and_mapped(monkeypatch):
    import socket
    from witness.web import assert_public_url

    for bad in ("http://[64:ff9b::7f00:1]/", "http://[64:ff9b::a9fe:a9fe]/",
                "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/"):
        with pytest.raises(WebError):
            assert_public_url(bad)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [
        (2, 1, 6, "", ("93.184.216.34", 0))])
    assert_public_url("https://example.org/")


class RedirectResponse:
    def __init__(self, status, location=None, body=b"", headers=None):
        self.status_code = status
        self.headers = dict(headers or {})
        if location is not None:
            self.headers["Location"] = location
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        self.closed = True


def test_gateway_never_follows_redirects_itself():
    from witness.web import fetch_public

    seen = []

    def get(url, **kwargs):
        seen.append(kwargs.get("allow_redirects"))
        return RedirectResponse(200, body=b"ok")

    fetched = fetch_public("https://example.org/a", sender=get)
    assert fetched.body == b"ok"
    assert seen == [False]


def test_gateway_validates_each_redirect_before_requesting():
    from witness.web import fetch_public

    requested = []

    def get(url, **kwargs):
        requested.append(url)
        if len(requested) == 1:
            return RedirectResponse(302, location="http://127.0.0.1/secret")
        raise AssertionError("private hop was requested")

    with pytest.raises(WebError):
        fetch_public("https://example.org/a", sender=get)
    assert requested == ["https://example.org/a"]


def test_gateway_follows_public_redirects():
    from witness.web import fetch_public

    def get(url, **kwargs):
        if url == "https://example.org/a":
            return RedirectResponse(302, location="/b")
        return RedirectResponse(200, body=b"there")

    fetched = fetch_public("https://example.org/a", sender=get)
    assert fetched.body == b"there"
    assert fetched.url == "https://example.org/b"


def test_gateway_refuses_endless_redirects():
    from witness.web import fetch_public

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return RedirectResponse(302, location="/loop")

    with pytest.raises(WebError):
        fetch_public("https://example.org/a", sender=get)
    assert len(calls) == 5


def test_gateway_bounds_bytes_and_closes():
    from witness.web import fetch_public

    resp = RedirectResponse(200, body=b"x" * 100)
    fetched = None
    with pytest.raises(WebError):
        fetched = fetch_public("https://example.org/a", sender=lambda u, **k: resp,
                               max_bytes=10)
    assert fetched is None
    assert resp.closed is True


def test_pinned_send_connects_to_the_validated_ip(monkeypatch):
    import io
    import socket
    import ssl
    from witness import web

    created = {}
    wrapped = {}

    class FakeSock:
        def settimeout(self, timeout):
            pass

        def sendall(self, data):
            pass

        def makefile(self, mode, *args):
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        def close(self):
            pass

    def create_connection(address, timeout=None):
        created["address"] = address
        return FakeSock()

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            wrapped["server_hostname"] = server_hostname
            return sock

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(ssl, "create_default_context", lambda: FakeContext())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [
        (2, 1, 6, "", ("93.184.216.34", 0))])
    fetched = web.fetch_public("https://example.org/a")
    assert fetched.body == b"ok"
    assert created["address"][0] == "93.184.216.34"
    assert wrapped["server_hostname"] == "example.org"


def test_web_error_strips_query_strings():
    err = ConnectionError(
        "failed for url: /w/api.php?ggscoord=52.15965|4.35321&format=json")
    get = FakeTransport([err, err, err])
    with pytest.raises(WebError) as excinfo:
        mediawiki_get(get, "https://nl.wikipedia.org/w/api.php",
                      {"ggscoord": "52.15965|4.35321"}, sleep=lambda s: None)
    assert "nl.wikipedia.org" in str(excinfo.value)
    assert "ggscoord" not in str(excinfo.value)
    assert "52.15965" not in str(excinfo.value)


def test_body_read_honours_the_total_deadline(monkeypatch):
    import time

    from witness import web

    class Slow:
        status_code = 200
        headers = {}
        url = "https://example.org/"

        def iter_content(self, n):
            for _ in range(4):
                time.sleep(0.3)
                yield b"x"

        def close(self):
            pass

    monkeypatch.setattr(web, "assert_public_url", lambda url: None)
    started = time.monotonic()
    with pytest.raises(web.WebError) as excinfo:
        web.fetch_public("https://example.org/", sender=lambda *a, **k: Slow(),
                         total_timeout=0.1)
    assert time.monotonic() - started < 1.0
    assert "total time" in str(excinfo.value)


def test_redirect_location_matches_case_insensitively(monkeypatch):
    from witness import web

    calls = []

    class Redirect:
        status_code = 302
        headers = {"location": "/next"}

        def close(self):
            pass

    class Final:
        status_code = 200
        headers = {}
        url = "https://example.org/next"
        content = b"done"

        def close(self):
            pass

    def sender(url, **kwargs):
        calls.append(url)
        return Final() if url.endswith("/next") else Redirect()

    monkeypatch.setattr(web, "assert_public_url", lambda url: None)
    got = web.fetch_public("https://example.org/", sender=sender)
    assert got.body == b"done"
    assert calls == ["https://example.org/", "https://example.org/next"]


def test_https_never_downgrades_to_http(monkeypatch):
    from witness import web

    class Redirect:
        status_code = 302
        headers = {"Location": "http://example.org/plain"}

        def close(self):
            pass

    monkeypatch.setattr(web, "assert_public_url", lambda url: None)
    with pytest.raises(web.WebError) as excinfo:
        web.fetch_public("https://example.org/",
                         sender=lambda *a, **k: Redirect())
    assert "https to http" in str(excinfo.value)


def test_post_body_never_resent_on_307_and_308(monkeypatch):
    from witness import web

    for status in (307, 308):
        sent = []

        class Redirect:
            status_code = status
            headers = {"Location": "https://example.org/other"}

            def close(self):
                pass

        def sender(url, **kwargs):
            sent.append((url, kwargs.get("data")))
            return Redirect()

        monkeypatch.setattr(web, "assert_public_url", lambda url: None)
        with pytest.raises(web.WebError) as excinfo:
            web.fetch_public("https://example.org/overpass", sender=sender,
                             data=b"coords in the body")
        assert "POST" in str(excinfo.value)
        assert sent == [("https://example.org/overpass", b"coords in the body")]


def test_get_redirect_307_is_followed_without_a_body(monkeypatch):
    from witness import web

    class Redirect:
        status_code = 307
        headers = {"Location": "/other"}

        def close(self):
            pass

    class Final:
        status_code = 200
        headers = {}
        url = "https://example.org/other"
        content = b"done"

        def close(self):
            pass

    def sender(url, **kwargs):
        assert kwargs.get("data") is None
        return Final() if url.endswith("/other") else Redirect()

    monkeypatch.setattr(web, "assert_public_url", lambda url: None)
    got = web.fetch_public("https://example.org/", sender=sender)
    assert got.body == b"done"
