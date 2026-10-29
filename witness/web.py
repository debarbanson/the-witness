"""Shared plumbing for the free sources: one User-Agent, polite retries."""

import ipaddress
import re
import socket
import time
from urllib.parse import urlparse

USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"


class WebError(Exception):
    """A free source answered with an error after retries."""


def scrub_query(text) -> str:
    """Drop query strings from error text; coordinates travel in them."""
    return re.sub(r"(\?)[^\s\"']*", "?", str(text))


def assert_public_url(url) -> None:
    """Refuse server-side fetches to non-public addresses.

    Model-supplied URLs are fetched server-side, so literal private,
    loopback and link-local addresses are blocked, as are hostnames
    that resolve only to such addresses. An unresolvable hostname is
    allowed through: the fetch itself fails, and there is nothing to
    protect. DNS is resolved at check time, so a rebinding response
    between the check and the fetch is not covered.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host:
        raise WebError(f"refusing to fetch URL: {urlparse(url).scheme or 'no scheme'}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise WebError(f"refusing to fetch non-public address {host}")
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return
    ips = [info[4][0] for info in infos]
    if ips and not any(ipaddress.ip_address(ip).is_global for ip in ips):
        raise WebError(f"refusing to fetch {host}: non-public addresses")


RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_BACKOFF = (2, 4)
BUSY_BACKOFF = 5
RETRY_CODES = frozenset({"ratelimited", "maxlag", "cirrussearch-too-busy-error"})


def _retryable(exc: Exception) -> bool:
    """Transport errors and rate-limit/server statuses; never client errors."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status is None or status in RETRY_STATUS


def mediawiki_get(get, url, params, sleep=time.sleep, timeout=15, cache=None, tries=3):
    """GET a MediaWiki API, retrying transport errors and 429/5xx with
    backoff, and backing off once on ratelimited/maxlag."""
    key = cache_key(url, params)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    last = None
    for attempt in range(max(tries, 1)):
        try:
            resp = get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - retried with backoff below
            if attempt == tries - 1 or not _retryable(exc):
                raise WebError(scrub_query(f"{url}: {exc}")) from exc
            sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            continue
        data = resp.json()
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
