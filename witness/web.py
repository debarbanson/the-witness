"""Shared plumbing for the free sources: one User-Agent, polite retries."""

import time

USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"


class WebError(Exception):
    """A free source answered with an error after retries."""


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
                raise WebError(f"{url}: {exc}") from exc
            sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            continue
        data = resp.json()
        error = data.get("error") or {}
        last = error
        if error.get("code") in RETRY_CODES and attempt < tries - 1:
            sleep(BUSY_BACKOFF)
            continue
        if error:
            raise WebError(f"{url}: {error.get('info', error)}")
        if cache is not None:
            cache.put(key, data)
        return data
    raise WebError(f"{url}: {(last or {}).get('info', last)}")


def cache_key(url, params) -> str:
    return url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
