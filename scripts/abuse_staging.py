"""Abuse checks against staging. One real Modal path, never the fake
provider alone: each check runs against the deployed staging app, and
checks marked fake provider need WITNESS_FAKE_PROVIDER=1 (with
WITNESS_FAKE_DELAY_S=2 so cancels land mid-call) in the staging
environment.

Staging also needs WITNESS_ABUSE_RESET=1 so the script can reset the
film and visitor quotas between cases; without it the script refuses
to run. Spend totals are never reset.

Every check asserts on effects, not on status labels: ledger counts
(films admitted, paid reconciliations) through /api/debug/ledger,
paid calls frozen after a halt, film bytes fetchable through the
capability URL, the served photo free of metadata, 429s with a quota
error, and retention ends set. A status label only tells the script
when to stop waiting.
"""

import io
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from PIL import Image
from PIL.PngImagePlugin import PngInfo

CHECKS = []


def check(name, fake_provider):
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


def _ledger(client):
    out = client.get("/api/debug/ledger")
    assert out.status_code == 200, out.text[:200]
    return out.json()


def _reset(client):
    out = client.post("/api/debug/reset-quotas")
    assert out.status_code == 200, (
        "staging needs WITNESS_ABUSE_RESET=1 for the abuse run")
    return out.json()


def _start(client, photo=None, **data):
    files = {"photo": ("up.jpg", photo or _photo())}
    out = client.post("/api/jobs", files=files, data={"ack": "on", **data},
                      headers={"Origin": _origin(str(client.base_url))})
    assert out.status_code == 200, out.text[:200]
    return out.json()["job_id"]


def _wait(client, job_id, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "cancelled", "failed", "expired"):
            return state
        time.sleep(2.0)
    raise AssertionError("job never finished")


def _wait_for_confirm(client, job_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state.get("confirm"):
            return state
        time.sleep(1.0)
    raise AssertionError("no confirm asked")


def _film_bytes(client, film_url):
    out = client.get(film_url)
    assert out.status_code == 200, out.text[:200]
    assert len(out.content) > 1000, "a film page is not empty"
    return out.content


def _today_photo(client, film_url):
    url = film_url.rstrip("/") + "/today.jpg"
    out = client.get(url)
    assert out.status_code == 200, f"no served photo at {url}"
    shot = Image.open(io.BytesIO(out.content))
    assert shot.format == "JPEG"
    assert shot.info.get("exif") is None, "EXIF survived"
    assert shot.info.get("icc_profile") is None, "ICC survived"
    assert not shot.info.get("comment"), "comment survived"
    assert not any("xml" in str(key).lower()
                   for key in shot.info), "XMP survived"
    shot.load()
    return shot


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
    assert _ledger(client)["films"] == 0, "reads admit no films"


@check("missing acknowledgement refused", fake_provider=False)
def ack(client):
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo())})
    assert out.status_code == 400
    assert _ledger(client)["films"] == 0, "a refused upload is not admitted"


@check("metadata stripped from the served photo", fake_provider=True)
def uploads(client):
    info = PngInfo()
    info.add_text("XML:com.adobe.xmp", "<xmp>private</xmp>")
    info.add_text("Comment", "private")
    buf = io.BytesIO()
    Image.new("RGB", (24, 16)).save(buf, format="PNG", pnginfo=info,
                                     icc_profile=b"fake")
    job = _start(client, photo=buf.getvalue(), place="Test Town")
    state = client.get(f"/api/jobs/{job}").json()
    if state.get("confirm"):
        client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    final = _wait(client, job)
    film_url = (final.get("result") or {}).get("film_url")
    assert film_url, final
    _film_bytes(client, film_url)
    _today_photo(client, film_url)
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
    assert _ledger(client)["films"] == 1, "three confirms admitted once"
    film_url = (final.get("result") or {}).get("film_url")
    assert film_url, final
    _film_bytes(client, film_url)


@check("decline stops the spending", fake_provider=True)
def decline(client):
    job = _start(client, place="Test Town")
    _wait_for_confirm(client, job)
    before = _ledger(client)["calls"]
    assert client.post(f"/api/jobs/{job}/decide",
                       json={"confirm": False}).status_code == 200
    final = _wait(client, job)
    assert _ledger(client)["calls"] == before, "no paid call after decline"
    assert "film_url" not in (final.get("result") or {}), final


@check("cancel mid-job halts the spending", fake_provider=True)
def cancel(client):
    job = _start(client, place="Test Town")
    time.sleep(3.0)  # worker is inside slow fake calls
    before = _ledger(client)["calls"]
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert _ledger(client)["calls"] == before, "no paid call after cancel"
    assert final["ended_at"] is not None, final


@check("two visitors keep their own films", fake_provider=True)
def two_visitors(client, base):
    first, second = _client(base), _client(base)
    red = _start(first, photo=_photo("red"), place="Test Town")
    blue = _start(second, photo=_photo("blue"), place="Test Town")
    for job, owner in ((red, first), (blue, second)):
        _wait_for_confirm(owner, job)
        owner.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    done_red = _wait(first, red)
    done_blue = _wait(second, blue)
    assert _ledger(client)["films"] == 2, "two admissions counted"
    assert first.get(f"/api/jobs/{blue}").status_code == 403
    red_url = (done_red.get("result") or {}).get("film_url")
    blue_url = (done_blue.get("result") or {}).get("film_url")
    assert red_url and blue_url and red_url != blue_url
    _film_bytes(first, red_url)
    _film_bytes(second, blue_url)


@check("per-visitor quota refuses the third film", fake_provider=False)
def quota(client):
    first = _start(client, place="Test Town")
    second = _start(client, place="Test Town")
    out = client.post("/api/jobs", files={"photo": ("up.jpg", _photo())},
                      data={"ack": "on", "place": "Test Town"})
    assert out.status_code == 429, out.text[:200]
    assert "quota" in out.json()["error"].lower()
    assert _ledger(client)["films"] == 2, "the refused film is not counted"
    client.delete(f"/api/jobs/{first}")
    client.delete(f"/api/jobs/{second}")


@check("cancel after research ends the spending", fake_provider=True)
def cancel_after_research(client):
    job = _start(client, place="Test Town")
    _wait_for_confirm(client, job)
    client.post(f"/api/jobs/{job}/decide", json={"confirm": True})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        events = client.get(f"/api/jobs/{job}").json()["events"]
        if any(event["event"] == "painting" for event in events):
            break
        time.sleep(1.0)
    else:
        raise AssertionError("research never reached painting")
    before = _ledger(client)["calls"]
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert _ledger(client)["calls"] == before, "no paid call after cancel"
    assert final["ended_at"] is not None, final


@check("closed tab cancels through the beacon endpoint",
       fake_provider=False)
def closed_tab(client):
    job = _start(client, place="Test Town")
    before = _ledger(client)["calls"]
    out = client.post(f"/api/jobs/{job}/cancel")  # what sendBeacon calls
    assert out.status_code == 200, out.text[:200]
    final = _wait(client, job)
    assert _ledger(client)["calls"] == before, "no paid call after cancel"
    assert final["ended_at"] is not None, final


def _sizes():
    from witness import photo as photo_module
    from witness import webapp as webapp_module

    cap = photo_module.MAX_UPLOAD_BYTES
    return cap, webapp_module.FORM_SLACK_BYTES


@check("oversize body refused before reading", fake_provider=False)
def oversize(client):
    cap, _slack = _sizes()
    body = b"\xff\xd8" + b"0" * (cap + 1_000_000)  # past the middleware cap
    started = time.monotonic()
    out = client.post("/api/jobs", files={"photo": ("p.jpg", body)},
                      data={"ack": "on"})
    assert out.status_code == 400, out.text[:200]
    assert time.monotonic() - started < 10, "refusal must precede the spool"
    assert _ledger(client)["films"] == 0, "a refused upload is not admitted"


@check("handler spool refuses before admission", fake_provider=False)
def spool(client):
    from witness import webapp as webapp_module

    cap, slack = _sizes()
    body = b"\xff\xd8" + b"0" * (cap + 100)  # past the spool, under the cap
    assert len(body) < cap + slack
    out = client.post("/api/jobs", files={"photo": ("p.jpg", body)},
                      data={"ack": "on"})
    assert out.status_code == 400, out.text[:200]
    assert _ledger(client)["films"] == 0, "a refused upload is not admitted"


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
    assert _ledger(client)["films"] == 0, "a refused upload is not admitted"


@check("cookieless quota refuses the third film", fake_provider=False)
def cookieless_quota(client, base):
    outs = []
    for _ in range(3):  # fresh client = no vid cookie, like curl
        fresh = _client(base)
        outs.append(fresh.post("/api/jobs",
                               files={"photo": ("up.jpg", _photo())},
                               data={"ack": "on", "place": "Test Town"}))
    assert [out.status_code for out in outs] == [200, 200, 429]
    assert _ledger(client)["films"] == 2, "the refused film is not counted"


@check("cancel racing progress writes ends cancelled", fake_provider=True)
def cancel_race(client):
    job = _start(client, place="Test Town")
    time.sleep(3.0)  # worker is inside slow fake calls
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    for _ in range(10):  # polls race the worker's progress writes
        state = client.get(f"/api/jobs/{job}").json()
        if state["status"] == "cancelled":
            break
    before = _ledger(client)["calls"]
    final = _wait(client, job)
    assert _ledger(client)["calls"] == before, "no paid call after cancel"
    assert final["ended_at"] is not None, final


@check("cancelled job carries its retention end", fake_provider=False)
def retention_end(client):
    job = _start(client, place="Test Town")
    assert client.delete(f"/api/jobs/{job}").status_code == 200
    final = _wait(client, job)
    assert final["ended_at"] is not None, "nothing to prune by"


def main(base):
    probe = _client(base)
    try:
        _reset(probe)
    except AssertionError as exc:
        print(f"REFUSED {exc}")
        return 1
    failed = 0
    for name, fn, fake_provider in CHECKS:
        via = "staging, fake provider" if fake_provider else "staging"
        client = _client(base)  # fresh visitor cookie per case
        try:
            _reset(client)
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
