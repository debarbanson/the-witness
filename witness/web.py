"""Shared plumbing for the free sources: one fetch gateway, one User-Agent."""

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlparse, urlsplit

USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"


class WebError(Exception):
    """A free source answered with an error after retries.

    `refused` marks a gateway refusal (blocked address, redirect loop,
    byte cap): retrying cannot help. `limit` names the cap hit
    ("bytes", "hops", "time"), if any."""


def _refuse(message, limit=None) -> WebError:
    err = WebError(message)
    err.refused = True
    err.limit = limit
    return err


def scrub_query(text) -> str:
    """Drop query strings from error text; coordinates travel in them."""
    return re.sub(r"(\?)[^\s\"']*", "?", str(text))


NAT64_NET = ipaddress.ip_network("64:ff9b::/96")
SIXTO4_NET = ipaddress.ip_network("2002::/16")


def _is_public_ip(raw: str) -> bool:
    """True only for globally routable addresses. IPv6 transition
    tricks are unwrapped first: NAT64, 6to4 and IPv4-mapped addresses
    count as the IPv4 address they hide."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in NAT64_NET:
            return _is_public_ip(str(ipaddress.ip_address(int(ip) & 0xFFFFFFFF)))
        if ip in SIXTO4_NET:
            return _is_public_ip(str(ipaddress.ip_address((int(ip) >> 80) & 0xFFFFFFFF)))
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped.is_global
    return ip.is_global


def resolve_public_ips(host: str) -> list:
    """Every address a hostname resolves to, or [] when it does not
    resolve. Raises when any address is non-public: one bad answer
    poisons the host, since the connection may use any of them."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    ips = []
    for info in infos:
        raw = info[4][0]
        if not _is_public_ip(raw):
            raise _refuse(f"refusing to fetch {host}: non-public addresses")
        ips.append(raw)
    return ips


def assert_public_url(url) -> None:
    """Refuse server-side fetches to non-public addresses.

    Model-supplied URLs are fetched server-side, so literal private,
    loopback and link-local addresses are blocked, as is any hostname
    with a non-public answer. An unresolvable hostname is allowed
    through: the fetch itself fails, and there is nothing to protect.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host:
        raise _refuse(f"refusing to fetch URL: {parsed.scheme or 'no scheme'}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public_ip(host):
            raise _refuse(f"refusing to fetch non-public address {host}")
        return
    resolve_public_ips(host)


RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_BACKOFF = (2, 4)
BUSY_BACKOFF = 5
RETRY_CODES = frozenset({"ratelimited", "maxlag", "cirrussearch-too-busy-error"})

MAX_REDIRECT_HOPS = 5
MAX_FETCH_BYTES = 2_000_000


def _retryable(exc: Exception) -> bool:
    """Transport errors and rate-limit/server statuses; never client
    errors and never gateway refusals."""
    if getattr(exc, "refused", False):
        return False
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status is None or status in RETRY_STATUS


class _HttpStatusError(Exception):
    """A status code shaped like a transport error, for retry checks."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = type("Resp", (), {"status_code": status})()


@dataclass
class Fetched:
    """One gateway answer: final URL, status, headers, capped body."""

    url: str
    status: int
    headers: dict
    body: bytes


def _read_capped(resp, max_bytes: int, deadline=None) -> bytes:
    """Read a response body up to the cap, closing on every path. The
    total deadline is enforced while reading, not just before."""
    chunks, size = [], 0
    try:
        if hasattr(resp, "iter_content"):
            pieces = resp.iter_content(65536)
        elif hasattr(resp, "read"):
            pieces = iter(lambda: resp.read(65536), b"")
        elif hasattr(resp, "content"):
            pieces = [resp.content]
        elif hasattr(resp, "text"):
            pieces = [resp.text.encode("utf-8", "replace")]
        else:  # minimal doubles shaped for .json() only
            pieces = [json.dumps(resp.json()).encode("utf-8")]
        for piece in pieces:
            if deadline is not None and time.monotonic() > deadline:
                raise _refuse("fetch exceeded its total time", limit="time")
            if not piece:
                continue
            size += len(piece)
            if size > max_bytes:
                raise _refuse(f"page over {max_bytes} bytes, skipped",
                              limit="bytes")
            chunks.append(piece)
        return b"".join(chunks)
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()


class _PinnedResponse:
    """A requests-like skin over one pinned connection."""

    def __init__(self, conn, http_resp, url):
        self._conn = conn
        self._http_resp = http_resp
        self.url = url
        self.status_code = http_resp.status
        self.headers = dict(http_resp.getheaders())

    def iter_content(self, chunk_size=65536):
        while True:
            piece = self._http_resp.read(chunk_size)
            if not piece:
                return
            yield piece

    def close(self):
        self._conn.close()


def _pinned_send(url, params=None, data=None, headers=None, timeout=15,
                 **_ignored):
    """One request pinned to the validated address: resolve once, open
    the socket to that IP, and verify TLS for the real hostname via
    SNI. Nothing here follows redirects."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ips = resolve_public_ips(host)
    if not ips:
        raise WebError(f"cannot resolve {host}")
    query = urlencode(params or {})
    path = parsed.path or "/"
    if parsed.query or query:
        path += "?" + "&".join(p for p in (parsed.query, query) if p)
    body = urlencode(data) if data else None
    send_headers = {"Host": host, "User-Agent": USER_AGENT,
                    "Connection": "close"}
    send_headers.update(headers or {})
    if body is not None:
        send_headers.setdefault("Content-Type",
                                "application/x-www-form-urlencoded")
    sock = socket.create_connection((ips[0], port), timeout=timeout)
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        conn.request("POST" if data is not None else "GET", path,
                     body=body, headers=send_headers)
        return _PinnedResponse(conn, conn.getresponse(), url)
    except Exception:
        sock.close()
        raise


def fetch_public(url, sender=None, *, params=None, data=None, headers=None,
                 timeout=15, total_timeout=30, max_bytes=MAX_FETCH_BYTES,
                 max_hops=MAX_REDIRECT_HOPS, raise_status=False) -> Fetched:
    """One outbound fetch through the gateway: every hop is validated
    before it is requested, redirects are followed manually (at most 5),
    and the body is capped. `sender` is an injectable requests-like
    callable; without one the pinned stdlib sender is used. The
    response is always closed; the capped body is returned. With
    raise_status, a 4xx/5xx final status raises like a transport
    error (shaped for the retry checks)."""
    deadline = time.monotonic() + total_timeout
    current, hops = url, 0
    send = sender or _pinned_send
    while True:
        assert_public_url(current)
        if time.monotonic() > deadline:
            raise _refuse("fetch exceeded its total time", limit="time")
        if hops >= max_hops:
            raise _refuse(f"too many redirects (over {max_hops})",
                          limit="hops")
        hops += 1
        resp = send(current, params=params, data=data, headers=headers,
                    timeout=timeout, allow_redirects=False)
        status = getattr(resp, "status_code", 200)
        if status in (301, 302, 303, 307, 308):
            headers = getattr(resp, "headers", {}) or {}
            location = next((value for key, value in headers.items()
                             if key.lower() == "location"), None)
            close = getattr(resp, "close", None)
            if callable(close):
                close()
            if not location:
                raise WebError(f"redirect without Location at {current}")
            if data is not None and status in (307, 308):
                raise WebError(
                    "refused to resend a POST body on a "
                    f"{status} redirect from {current}")
            target = urljoin(current, location)
            if (urlsplit(current).scheme == "https"
                    and urlsplit(target).scheme == "http"):
                raise WebError(
                    f"refused redirect from https to http at {current}")
            current = target
            if status in (301, 302, 303):
                data = None  # redirected POSTs continue as GETs
            params = None
            continue
        body = _read_capped(resp, max_bytes, deadline)
        if raise_status and status >= 400:
            raise _HttpStatusError(status)
        return Fetched(url=getattr(resp, "url", None) or current,
                       status=status,
                       headers=dict(getattr(resp, "headers", {}) or {}),
                       body=body)


def mediawiki_get(get, url, params, sleep=time.sleep, timeout=15, cache=None, tries=3):
    """GET a MediaWiki API through the gateway, retrying transport
    errors and 429/5xx with backoff, and backing off once on
    ratelimited/maxlag."""
    key = cache_key(url, params)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    last = None
    for attempt in range(max(tries, 1)):
        try:
            fetched = fetch_public(
                url, sender=get, params=params,
                headers={"User-Agent": USER_AGENT}, timeout=timeout,
                raise_status=True)
        except Exception as exc:  # noqa: BLE001 - retried with backoff below
            if attempt == tries - 1 or not _retryable(exc):
                raise WebError(scrub_query(f"{url}: {exc}")) from exc
            sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            continue
        try:
            data = json.loads(fetched.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WebError(scrub_query(f"{url}: bad JSON ({exc})"))
        error = data.get("error") or {}
        last = error
        if error.get("code") in RETRY_CODES and attempt < tries - 1:
            sleep(BUSY_BACKOFF)
            continue
        if error:
            raise WebError(scrub_query(f"{url}: {error.get('info', error)}"))
        if cache is not None:
            cache.put(key, data)
        return data
    raise WebError(scrub_query(f"{url}: {(last or {}).get('info', last)}"))


def cache_key(url, params) -> str:
    return url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
