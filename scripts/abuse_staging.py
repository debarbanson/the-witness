"""Abuse tests against staging (fake provider on). Usage:

    python scripts/abuse_staging.py https://<modal-app-url>

Staging must run with WITNESS_FAKE_PROVIDER=1 and WITNESS_FAKE_DELAY_S=2
in its secret for the cancel test. Each check prints PASS/FAIL; the
exit code is nonzero when any check fails. No keys needed, none printed.
"""

import io
import sys
import time

import httpx
from PIL import Image
from PIL.PngImagePlugin import PngInfo

CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def _photo(color="blue", fmt="JPEG", **save_kwargs):
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _start(client, photo=None, **data):
    files = {"photo": ("up.jpg", photo or _photo())}
    out = client.post("/api/jobs", files=files, data={"ack": "on", **data})
    assert out.status_code == 200, out.text[:200]
    return out.json()["job_id"]


def _wait(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "cancelled"):
            return state
        time.sleep(2.0)
    raise AssertionError("job never finished")


@check("security headers on pages and examples")
def headers(client):
    for path in ("/", "/privacy", "/examples/de-adriaan"):
        out = client.get(path)
        assert out.status_code == 200, path
        assert out.headers["X-Content-Type-Options"] == "nosniff"
        assert out.headers["Referrer-Policy"] == "no-referrer"
        csp = out.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'nonce-" in csp


@check("missing acknowledgement refused")
def ack(client):
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo())})
    assert out.status_code == 400


@check("metadata and malformed uploads handled")
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


@check("repeated confirmation stays one film")
def repeated_confirm(client):
    job = _start(client, place="Test Town")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job}").json()
        if state.get("confirm"):
            break
        time.sleep(1.0)
    assert state.get("confirm"), "no confirm asked"
    for _ in range(3):
        out = client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
        assert out.status_code == 200
    final = _wait(client, job)
    assert final["status"] == "done", final


@check("decline spends nothing and ends honestly")
def decline(client):
    job = _start(client, place="Test Town")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job}").json()
        if state.get("confirm"):
            break
        time.sleep(1.0)
    assert state.get("confirm"), "no confirm asked"
    assert client.post(f"/api/jobs/{job}/decide",
                       json={"confirm": False}).status_code == 200
    final = _wait(client, job)
    assert final["result"]["message"].startswith("Not confirmed"), final


@check("cancel mid-job halts it")
def cancel(client):
    job = _start(client, place="Test Town")
    time.sleep(3.0)  # worker is inside slow fake calls
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert final["status"] == "cancelled", final


@check("two visitors keep their own photos")
def two_visitors(client, base):
    first, second = httpx.Client(base_url=base), httpx.Client(base_url=base)
    red = _start(first, photo=_photo("red"), place="Test Town")
    blue = _start(second, photo=_photo("blue"), place="Test Town")
    for job, owner in ((red, first), (blue, second)):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if owner.get(f"/api/jobs/{job}").json().get("confirm"):
                break
            time.sleep(1.0)
        owner.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    done_red = _wait(first, red)
    done_blue = _wait(second, blue)
    assert done_red["status"] == "done" and done_blue["status"] == "done"
    assert first.get(f"/api/jobs/{blue}").status_code == 403


@check("per-visitor quota refuses the third film")
def quota(client):
    jobs = [_start(client, place="Test Town") for _ in range(3)]
    messages = []
    for job in jobs:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = client.get(f"/api/jobs/{job}").json()
            if state.get("confirm") or state["status"] == "done":
                break
            time.sleep(1.0)
        if state.get("confirm"):
            client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
        final = _wait(client, job, timeout=240)
        messages.append(str((final.get("result") or {}).get("message", "")))
    assert any("quota" in message.lower() for message in messages), messages


def main(base):
    client = httpx.Client(base_url=base, timeout=30.0)
    failed = 0
    for name, fn in CHECKS:
        try:
            if fn.__code__.co_argcount == 2:
                fn(client, base)
            else:
                fn(client)
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
