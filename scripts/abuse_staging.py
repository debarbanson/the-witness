"""Abuse tests against staging (fake provider on). Usage:

    python scripts/abuse_staging.py https://<modal-app-url>

Staging must run with WITNESS_FAKE_PROVIDER=1 and WITNESS_FAKE_DELAY_S=2
in its secret for the cancel tests. Each check prints PASS/FAIL with
its path: "staging" exercises the real Modal web, worker, store and
ledger; "staging, fake provider" additionally needs the fake model
(with its delay) to hold a window open. The exit code is nonzero when
any check fails. No keys needed, none printed.
"""

import io
import sys
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image
from PIL.PngImagePlugin import PngInfo

CHECKS = []


def check(name, *, fake_provider):
    """Register a check, declaring whether it needs the fake provider
    (True) or exercises the real Modal path alone (False)."""

    def wrap(fn):
        CHECKS.append((name, fn, fake_provider))
        return fn

    return wrap


def _origin(base):
    parts = urlsplit(base)
    host = parts.hostname or ""
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    return f"{parts.scheme or 'https'}://{host}"


def _client(base):
    return httpx.Client(base_url=base, timeout=30.0,
                        headers={"Origin": _origin(base)})


def _photo(color="blue", fmt="JPEG", **save_kwargs):
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _start(client, photo=None, **data):
    files = {"photo": ("up.jpg", photo or _photo())}
    out = client.post("/api/jobs", files=files, data={"ack": "on", **data},
                      headers={"Origin": _origin(str(client.base_url))})
    assert out.status_code == 200, out.text[:200]
    return out.json()["job_id"]


def _wait(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "cancelled", "failed", "expired"):
            return state
        time.sleep(2.0)
    raise AssertionError("job never finished")


def _wait_for_confirm(client, job_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state.get("confirm"):
            return state
        time.sleep(1.0)
    raise AssertionError("no confirm asked")


@check("security headers on pages and examples", fake_provider=False)
def headers(client):
    for path in ("/", "/privacy", "/examples/de-adriaan"):
        out = client.get(path)
        assert out.status_code == 200, path
        assert out.headers["X-Content-Type-Options"] == "nosniff"
        assert out.headers["Referrer-Policy"] == "no-referrer"
        csp = out.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'nonce-" in csp
        assert "'unsafe-inline'" not in csp


@check("missing acknowledgement refused", fake_provider=False)
def ack(client):
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo())})
    assert out.status_code == 400


@check("metadata and malformed uploads handled", fake_provider=True)
def uploads(client):
    info = PngInfo()
    info.add_text("XML:com.adobe.xmp", "<xmp>private</xmp>")
    buf = io.BytesIO()
    Image.new("RGB", (24, 16)).save(buf, format="PNG", pnginfo=info,
                                     icc_profile=b"fake")
    job = _start(client, photo=buf.getvalue(), place="Test Town")
    _wait(client, job)
    bad = client.post("/api/jobs", files={"photo": ("up.jpg", b"junk" * 64)},
                      data={"ack": "on"})
    assert bad.status_code == 400


@check("repeated confirmation stays one film", fake_provider=True)
def repeated_confirm(client):
    job = _start(client, place="Test Town")
    _wait_for_confirm(client, job)
    for _ in range(3):
        out = client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
        assert out.status_code == 200
    final = _wait(client, job)
    assert final["status"] == "done", final


@check("decline spends nothing and ends honestly", fake_provider=True)
def decline(client):
    job = _start(client, place="Test Town")
    _wait_for_confirm(client, job)
    assert client.post(f"/api/jobs/{job}/decide",
                       json={"confirm": False}).status_code == 200
    final = _wait(client, job)
    assert final["result"]["message"].startswith("Not confirmed"), final


@check("cancel mid-job halts it", fake_provider=True)
def cancel(client):
    job = _start(client, place="Test Town")
    time.sleep(3.0)  # worker is inside slow fake calls
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert final["status"] == "cancelled", final
    assert final["ended_at"] is not None, final


@check("two visitors keep their own photos", fake_provider=True)
def two_visitors(client, base):
    first, second = _client(base), _client(base)
    red = _start(first, photo=_photo("red"), place="Test Town")
    blue = _start(second, photo=_photo("blue"), place="Test Town")
    for job, owner in ((red, first), (blue, second)):
        _wait_for_confirm(owner, job)
        owner.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    done_red = _wait(first, red)
    done_blue = _wait(second, blue)
    assert done_red["status"] == "done" and done_blue["status"] == "done"
    assert first.get(f"/api/jobs/{blue}").status_code == 403


@check("per-visitor quota refuses the third film", fake_provider=False)
def quota(client):
    first = _start(client, place="Test Town")
    second = _start(client, place="Test Town")
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo())},
                      data={"ack": "on", "place": "Test Town"})
    assert out.status_code == 429, out.text[:200]
    assert "quota" in out.json()["error"].lower()
    client.delete(f"/api/jobs/{first}")
    client.delete(f"/api/jobs/{second}")


@check("cancel after research ends it", fake_provider=True)
def cancel_after_research(client):
    job = _start(client, place="Test Town")
    _wait_for_confirm(client, job)
    client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        events = client.get(f"/api/jobs/{job}").json()["events"]
        if any(event["event"] == "painting" for event in events):
            break
        time.sleep(1.0)
    else:
        raise AssertionError("research never reached painting")
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert final["status"] == "cancelled", final
    assert final["ended_at"] is not None, final


@check("closed tab cancels through the beacon endpoint",
       fake_provider=False)
def closed_tab(client):
    job = _start(client, place="Test Town")
    out = client.post(f"/api/jobs/{job}/cancel")  # what sendBeacon calls
    assert out.status_code == 200, out.text[:200]
    final = _wait(client, job)
    assert final["status"] == "cancelled", final


@check("oversize body refused before reading", fake_provider=False)
def oversize(client):
    big = b"\xff\xd8" + b"0" * 6_000_000
    started = time.monotonic()
    out = client.post("/api/jobs", files={"photo": ("p.jpg", big)},
                      data={"ack": "on"})
    assert out.status_code == 400, out.text[:200]
    assert time.monotonic() - started < 10, "refusal must precede the spool"


@check("foreign and missing origins refused", fake_provider=False)
def origins(client, base):
    bare = httpx.Client(base_url=base, timeout=30.0)
    missing = bare.post("/api/jobs", files={"photo": ("up.jpg", _photo())},
                        data={"ack": "on"})
    assert missing.status_code == 403, missing.text[:200]
    foreign = bare.post("/api/jobs", files={"photo": ("up.jpg", _photo())},
                        data={"ack": "on"},
                        headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403, foreign.text[:200]
    assert "nosniff" in foreign.headers.get("X-Content-Type-Options", "")


@check("cookieless quota refuses the third film", fake_provider=False)
def cookieless_quota(client, base):
    outs = []
    for _ in range(3):  # fresh client = no vid cookie, like curl
        fresh = _client(base)
        outs.append(fresh.post("/api/jobs",
                               files={"photo": ("up.jpg", _photo())},
                               data={"ack": "on", "place": "Test Town"}))
    assert [out.status_code for out in outs] == [200, 200, 429]


@check("cancel racing progress writes ends cancelled", fake_provider=True)
def cancel_race(client):
    job = _start(client, place="Test Town")
    time.sleep(3.0)  # worker is inside slow fake calls
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    for _ in range(10):  # polls race the worker's progress writes
        state = client.get(f"/api/jobs/{job}").json()
        if state["status"] == "cancelled":
            break
    final = _wait(client, job)
    assert final["status"] == "cancelled", final
    assert final["ended_at"] is not None, final


@check("cancelled job carries its retention end", fake_provider=False)
def retention_end(client):
    job = _start(client, place="Test Town")
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert final["status"] == "cancelled", final
    assert final["ended_at"] is not None, "nothing to prune by"


def main(base):
    client = _client(base)
    failed = 0
    for name, fn, fake_provider in CHECKS:
        via = "staging, fake provider" if fake_provider else "staging"
        try:
            if fn.__code__.co_argcount == 2:
                fn(client, base)
            else:
                fn(client)
        except Exception as exc:
            failed += 1
            print(f"FAIL {name} [{via}]: {exc}")
        else:
            print(f"PASS {name} [{via}]")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
