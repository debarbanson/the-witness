"""Shared plumbing for the free sources: one User-Agent, polite retries."""

import time

USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"


class WebError(Exception):
    """A free source answered with an error after retries."""


def mediawiki_get(get, url, params, sleep=time.sleep, timeout=90):
    """GET a MediaWiki API, backing off once on ratelimited/maxlag."""
    last = None
    for attempt in (0, 1):
        resp = get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        error = data.get("error") or {}
        if not error:
            return data
        last = error
        if error.get("code") in ("ratelimited", "maxlag") and attempt == 0:
            sleep(5)
    raise WebError(f"{url}: {(last or {}).get('info', last)}")
