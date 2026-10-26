"""Probe 7: identify the object in the owner's phone photo (step 0).

Reads EXIF GPS with Pillow, queries Overpass for candidates within 300 m,
and asks muse-spark-1.3 with the photo which candidate it shows.

Privacy: coordinates are used for the lookup only. Nothing printed or saved
contains coordinates: the Overpass response is stripped to names, types and
distances before saving, and the uploaded photo is re-encoded without EXIF.
"""

import base64
import io
import json
import math

import requests
from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD

from probes.common import OUT, client, data_uri, response_json, save_json

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "TheWitness/0.1 (Meta hackathon demo, one lookup per photo)"

QUERY = """[out:json][timeout:25];
(
  nwr(around:300,{lat},{lon})[man_made=windmill];
  nwr(around:300,{lat},{lon})[man_made=lighthouse];
  nwr(around:300,{lat},{lon})[historic];
  nwr(around:300,{lat},{lon})[natural=tree][denotation];
);
out center tags;"""


def main() -> None:
    samples = OUT.parent.parent / "samples"  # repo root; OUT is out/probes
    photos = sorted(p for p in samples.glob("*") if p.is_file()) if samples.is_dir() else []
    if not photos:
        raise SystemExit("samples/ has no photo yet; add one phone photo and rerun")
    photo = photos[0]
    print(f"photo: {photo.name}")

    gps = read_gps(photo)
    print(f"gps_present={gps['present']} precision={gps['precision']}")
    if not gps["present"]:
        save_json("identify.json", {"photo": photo.name, "gps": gps})
        raise SystemExit("no EXIF GPS in this photo; typed place is the fallback")
    lat, lon = gps["lat"], gps["lon"]

    elements = overpass(lat, lon)
    # Coordinates never leave this function: keep names, types, distances only.
    del lat, lon
    candidates = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or "(unnamed)"
        kind = (
            tags.get("man_made")
            or tags.get("historic")
            or tags.get("natural")
            or el.get("type")
        )
        candidates.append(
            {
                "name": name,
                "kind": kind,
                "distance_m": el["_dist"],
                "wikidata": tags.get("wikidata"),
                "wikipedia": tags.get("wikipedia"),
            }
        )
    candidates.sort(key=lambda c: c["distance_m"])
    print(f"candidates={len(candidates)}")
    for c in candidates[:10]:
        print(f"- {c['distance_m']} m: {c['name']} ({c['kind']})")

    uri, _ = data_uri(photo, max_dim=1024)
    assert_no_exif(uri)
    shortlist = "\n".join(
        f"{i + 1}. {c['name']} ({c['kind']}, about {c['distance_m']} m away)"
        for i, c in enumerate(candidates[:10])
    )
    resp = client().responses.create(
        model="muse-spark-1.3",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "This photo was taken near the following known "
                            "objects from OpenStreetMap:\n" + shortlist
                            + "\nWhich one does the photo show? Answer with "
                            "its number and name first, then one sentence "
                            "of confidence. If none of them, say NONE."
                        ),
                    },
                    {"type": "input_image", "image_url": uri},
                ],
            }
        ],
    )
    data = response_json(resp)
    verdict = ""
    for item in data["output"]:
        if item.get("type") == "message":
            verdict = item["content"][0]["text"]
    print("pick:", verdict[:300])
    save_json(
        "identify.json",
        {
            "photo": photo.name,
            "gps": {"present": True, "precision": gps["precision"]},
            "candidates": candidates[:10],
            "pick": verdict,
            "check_response": data,
        },
    )


def read_gps(path) -> dict:
    """EXIF GPS as decimal degrees, plus a precision label (no coords shown)."""
    exif = Image.open(path).getexif()
    gps_ifd = exif.get_ifd(IFD.GPSInfo) if hasattr(exif, "get_ifd") else {}
    tags = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
    lat_ref = tags.get("GPSLatitudeRef")
    lon_ref = tags.get("GPSLongitudeRef")
    lat_val = tags.get("GPSLatitude")
    lon_val = tags.get("GPSLongitude")
    if not (lat_ref and lon_ref and lat_val and lon_val):
        return {"present": False, "precision": "none"}
    lat = _dms(lat_val, lat_ref)
    lon = _dms(lon_val, lon_ref)
    # Precision from the seconds' decimal places, without revealing values.
    decimals = max(_decimals(lat_val[2]), _decimals(lon_val[2]))
    approx_m = 30 / (10**decimals) if decimals <= 4 else 0.01
    label = f"DMS to {decimals} dp, about {approx_m:g} m"
    if "GPSAltitude" in tags:
        label += ", altitude present"
    if "GPSDOP" in tags:
        label += ", DOP present"
    return {"present": True, "precision": label, "lat": lat, "lon": lon}


def _dms(value, ref) -> float:
    deg = float(value[0]) + float(value[1]) / 60 + float(value[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def _decimals(value) -> int:
    text = str(float(value))
    return len(text.split(".")[1]) if "." in text else 0


def overpass(lat: float, lon: float) -> list:
    """One Overpass call with the app's User-Agent. Returns raw elements."""
    body = QUERY.format(lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    resp = requests.post(
        OVERPASS_URL,
        data={"data": body},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    if resp.status_code == 429:
        raise SystemExit("Overpass rate limited (429); wait and rerun")
    resp.raise_for_status()
    elements = resp.json().get("elements", [])
    for el in elements:
        point = el.get("center", el)
        el["_dist"] = round(_haversine(lat, lon, point["lat"], point["lon"]))
    return elements


def _haversine(lat1, lon1, lat2, lon2) -> float:
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def assert_no_exif(uri: str) -> None:
    """Prove the uploaded bytes carry no EXIF before sending them."""
    raw = base64.b64decode(uri.split(",", 1)[1])
    exif = Image.open(io.BytesIO(raw)).getexif()
    assert len(exif) == 0, "re-encoded upload still carries EXIF"
    print("upload_exif_stripped=True")


if __name__ == "__main__":
    main()
