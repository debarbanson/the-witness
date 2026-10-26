"""Shared plumbing for the free sources: one User-Agent, polite retries."""

import time

USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"


class WebError(Exception):
    """A free source answered with an error after retries."""


def mediawiki_get(get, url, params, sleep=time.sleep, timeout=90, cache=None):
    """GET a MediaWiki API, backing off once on ratelimited/maxlag."""
    key = cache_key(url, params)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    last = None
    for attempt in (0, 1):
        resp = get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        error = data.get("error") or {}
        last = error
        if error.get("code") in ("ratelimited", "maxlag") and attempt == 0:
            sleep(5)
            continue
        if error:
            raise WebError(f"{url}: {error.get('info', error)}")
        if cache is not None:
            cache.put(key, data)
        return data
    raise WebError(f"{url}: {(last or {}).get('info', last)}")


def cache_key(url, params) -> str:
    return url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
