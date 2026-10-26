"""Probe 7 (new step 0): identify the object in the owner's phone photo.

Broad Overpass query (named things with notable tags within 250 m) plus
Wikidata nearby items as a second source, trying both MediaWiki
list=geosearch on wikidata.org and the Wikidata Query Service
wikibase:around. Ranked by camera direction then distance, top 5 with
Wikipedia sitelinks (local language, user language, English) to
muse-spark-1.3 with the photo.

Privacy: coordinates are used for the lookups only. Nothing printed or
saved contains coordinates: responses are stripped to names, kinds,
distances and bearings, and the uploaded photo is re-encoded without EXIF.
"""

import base64
import io
import math
import time

import requests
from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD

from probes.common import OUT, client, data_uri, response_json, save_json

OVERPASS_INSTANCES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "the-witness/0.1 (https://github.com/debarbanson/the-witness)"
RADIUS_M = 250
DIRECTION_WINDOW_DEG = 35
# Probe constants: the photo was taken in the Netherlands, the user reads
# English. The pipeline will detect the country and read the browser lang.
LOCAL_LANG = "nl"
USER_LANG = "en"

QUERY = """[out:json][timeout:25];
nwr(around:{radius},{lat},{lon})[name][~"^(wikidata|wikipedia|heritage|historic|tourism|man_made)$"~"."];
out tags center;"""

WDQS_QUERY = """SELECT ?place ?placeLabel ?typeLabel ?location ?dist WHERE {{
  SERVICE wikibase:around {{
    ?place wdt:P625 ?location .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius_km}" .
    bd:serviceParam wikibase:distance ?dist .
  }}
  OPTIONAL {{ ?place wdt:P31 ?type . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{langs}". }}
}}
ORDER BY ?dist"""

_cache: dict = {}  # process memory only; coordinates are never written to disk


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
        raise SystemExit("no EXIF GPS in this photo; typed place is the fallback")
    direction = read_direction(photo)
    print(f"view_direction={direction}")
    lat, lon = gps["lat"], gps["lon"]

    wd_geo, wd_qs = wikidata_nearby(lat, lon)
    try:
        osm = overpass(lat, lon)
        osm_note = "ok"
    except SystemExit as exc:
        print(f"Overpass unavailable, continuing on Wikidata alone: {exc}")
        osm, osm_note = [], str(exc)
    print(f"overpass={len(osm)} wikidata_geosearch={len(wd_geo)} wikidata_wdqs={len(wd_qs)}")
    for label, items in (("geosearch", wd_geo), ("wdqs", wd_qs)):
        found = "Q2487636" in {i["qid"] for i in items}
        print(f"wikidata {label}: {len(items)} items, Q2487636 found={found}")

    candidates = merge(osm, wd_geo, wd_qs, lat, lon, direction)
    del lat, lon
    print("ranking:")
    for i, c in enumerate(candidates[:5]):
        print(
            f"{i + 1}. {c['name']} ({c['kind']}; {c['distance_m']} m; "
            f"bearing {c['bearing_deg']}; {c['source']}; {c['qid']}; "
            f"articles={c['articles']})"
        )

    uri, _ = data_uri(photo, max_dim=1024)
    assert_no_exif(uri)
    shortlist = "\n".join(
        f"{i + 1}. {c['name']} ({c['kind']}, about {c['distance_m']} m away, "
        f"bearing {c['bearing_deg']} degrees)"
        for i, c in enumerate(candidates[:5])
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
                            f"The camera faced about {direction} degrees. "
                            "Nearby known objects, ranked by view direction "
                            f"then distance:\n{shortlist}\nWhich one does "
                            "the photo show? Answer with its number and name "
                            "first, then one sentence of confidence. If none "
                            "of them, say NONE."
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
        "identify2.json",
        {
            "photo": photo.name,
            "gps": {"present": True, "precision": gps["precision"]},
            "view_direction_deg": direction,
            "overpass": osm_note,
            "second_source_comparison": {
                "geosearch_items": len(wd_geo),
                "wdqs_items": len(wd_qs),
                "geosearch_has_q2487636": "Q2487636" in {i["qid"] for i in wd_geo},
                "wdqs_has_q2487636": "Q2487636" in {i["qid"] for i in wd_qs},
            },
            "candidates": candidates[:5],
            "pick": verdict,
            "check_response": data,
        },
    )


def read_gps(path) -> dict:
    """EXIF GPS as decimal degrees, plus a precision label (no coords shown)."""
    tags = _gps_tags(path)
    lat_ref, lon_ref = tags.get("GPSLatitudeRef"), tags.get("GPSLongitudeRef")
    lat_val, lon_val = tags.get("GPSLatitude"), tags.get("GPSLongitude")
    if not (lat_ref and lon_ref and lat_val and lon_val):
        return {"present": False, "precision": "none"}
    lat = _dms(lat_val, lat_ref)
    lon = _dms(lon_val, lon_ref)
    decimals = max(_decimals(lat_val[2]), _decimals(lon_val[2]))
    approx_m = 30 / (10**decimals) if decimals <= 4 else 0.01
    label = f"DMS to {decimals} dp, about {approx_m:g} m"
    if "GPSAltitude" in tags:
        label += ", altitude present"
    if "GPSDOP" in tags:
        label += ", DOP present"
    return {"present": True, "precision": label, "lat": lat, "lon": lon}


def read_direction(path) -> int | None:
    """Camera compass direction in degrees, or None when the tag is missing."""
    tags = _gps_tags(path)
    value = tags.get("GPSImgDirection")
    if value is None:
        return None
    return round(float(value)) % 360


def _gps_tags(path) -> dict:
    exif = Image.open(path).getexif()
    gps_ifd = exif.get_ifd(IFD.GPSInfo) if hasattr(exif, "get_ifd") else {}
    return {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}


def _dms(value, ref) -> float:
    deg = float(value[0]) + float(value[1]) / 60 + float(value[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def _decimals(value) -> int:
    text = str(float(value))
    return len(text.split(".")[1]) if "." in text else 0


def overpass(lat: float, lon: float) -> list:
    """Broad nearby query with retry and a second instance. Raw elements."""
    key = ("overpass", round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    body = QUERY.format(radius=RADIUS_M, lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    last_error = ""
    for url in OVERPASS_INSTANCES:
        for attempt in (1, 2):
            try:
                resp = requests.post(
                    url,
                    data={"data": body},
                    headers={"User-Agent": USER_AGENT},
                    timeout=60,
                )
            except requests.RequestException as exc:
                last_error = f"{url} attempt {attempt}: {exc}"
                break  # next instance; no point hammering a dead one
            if resp.status_code in (429, 502):
                last_error = f"{url} attempt {attempt}: HTTP {resp.status_code}"
                print(f"Overpass {resp.status_code} at {url}, waiting 30 s")
                time.sleep(30)
                continue
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            _cache[key] = elements
            print(f"overpass ok via {url}")
            return elements
    raise SystemExit(f"Overpass failed on all instances ({last_error})")


def wikidata_nearby(lat: float, lon: float) -> tuple[list, list]:
    """Nearby Wikidata items via geosearch AND via WDQS, for comparison.

    Each item: {qid, label, lat, lon}. Coordinates stay in memory only.
    """
    geo = _wikidata_geosearch(lat, lon)
    qs = _wikidata_wdqs(lat, lon)
    return geo, qs


def _wikidata_geosearch(lat: float, lon: float) -> list:
    key = ("wd_geo", round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    resp = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat:.6f}|{lon:.6f}",
            "gsradius": RADIUS_M,
            "gsnamespace": 0,
            "gslimit": 50,
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["query"]["geosearch"]
    labels = _wb_labels([r["title"] for r in raw])
    items = [
        {"qid": r["title"], "label": labels.get(r["title"]), "lat": r["lat"], "lon": r["lon"]}
        for r in raw
    ]
    _cache[key] = items
    return items


def _wikidata_wdqs(lat: float, lon: float) -> list:
    key = ("wd_qs", round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    query = WDQS_QUERY.format(
        lat=f"{lat:.6f}",
        lon=f"{lon:.6f}",
        radius_km=f"{RADIUS_M / 1000}",
        langs=f"{LOCAL_LANG},{USER_LANG}",
    )
    resp = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=90,
    )
    resp.raise_for_status()
    items = []
    for row in resp.json()["results"]["bindings"]:
        qid = row["place"]["value"].rsplit("/", 1)[1]
        point = row["location"]["value"]  # "Point(lon lat)"
        coords = point.removeprefix("Point(").removesuffix(")").split()
        items.append(
            {
                "qid": qid,
                "label": row.get("placeLabel", {}).get("value"),
                "kind": row.get("typeLabel", {}).get("value"),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
            }
        )
    _cache[key] = items
    return items


def _wb_labels(qids: list) -> dict:
    """Wikidata labels in the local then user language, one batched call."""
    if not qids:
        return {}
    resp = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids[:50]),
            "props": "labels",
            "languages": f"{LOCAL_LANG}|{USER_LANG}",
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    labels = {}
    for qid, entity in resp.json().get("entities", {}).items():
        lang_labels = entity.get("labels", {})
        best = lang_labels.get(LOCAL_LANG) or lang_labels.get(USER_LANG)
        labels[qid] = best["value"] if best else qid
    return labels


def sitelinks(qids: list) -> dict:
    """Wikipedia article titles per Q id for the local, user and English langs."""
    langs = dict.fromkeys([LOCAL_LANG, USER_LANG, "en"])  # de-duplicated, ordered
    if not qids:
        return {}
    resp = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids[:50]),
            "props": "sitelinks",
            "sitefilter": "|".join(f"{lang}wiki" for lang in langs),
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    out = {}
    for qid, entity in resp.json().get("entities", {}).items():
        links = entity.get("sitelinks", {})
        out[qid] = {
            lang: links[f"{lang}wiki"]["title"]
            for lang in langs
            if f"{lang}wiki" in links
        }
    return out


def merge(osm: list, wd_geo: list, wd_qs: list, lat: float, lon: float, direction) -> list:
    """One ranked list, coordinates stripped: names, kinds, distances, bearings."""
    by_qid: dict = {}
    for el in osm:
        tags = el.get("tags", {})
        point = el.get("center", el)
        if "lat" not in point or "lon" not in point:
            continue
        kind = (
            tags.get("man_made")
            or tags.get("tourism")
            or tags.get("historic")
            or tags.get("heritage")
            or "named place"
        )
        by_qid[tags.get("wikidata", f"osm:{el.get('id')}")] = {
            "name": tags.get("name", "(unnamed)"),
            "kind": kind,
            "source": "osm",
            "qid": tags.get("wikidata"),
            "_lat": point["lat"],
            "_lon": point["lon"],
        }
    for item in wd_geo + wd_qs:
        if item["qid"] in by_qid:
            if by_qid[item["qid"]]["source"] == "osm":
                by_qid[item["qid"]]["source"] = "osm+wikidata"
            continue
        by_qid[item["qid"]] = {
            "name": item.get("label") or item["qid"],
            "kind": item.get("kind") or "wikidata item",
            "source": "wikidata",
            "qid": item["qid"],
            "_lat": item["lat"],
            "_lon": item["lon"],
        }
    articles = sitelinks([qid for qid in by_qid if qid.startswith("Q")])
    candidates = []
    for qid, c in by_qid.items():
        c["distance_m"] = round(_haversine(lat, lon, c["_lat"], c["_lon"]))
        c["bearing_deg"] = round(_bearing(lat, lon, c["_lat"], c["_lon"])) % 360
        del c["_lat"], c["_lon"]
        c["articles"] = articles.get(qid, {})
        candidates.append(c)
    if direction is None:
        candidates.sort(key=lambda c: c["distance_m"])
    else:
        candidates.sort(
            key=lambda c: (
                _angular_diff(direction, c["bearing_deg"]) > DIRECTION_WINDOW_DEG,
                c["distance_m"],
            )
        )
    return candidates


def _angular_diff(a: int, b: int) -> int:
    return abs((a - b + 180) % 360 - 180)


def _haversine(lat1, lon1, lat2, lon2) -> float:
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x))


def assert_no_exif(uri: str) -> None:
    """Prove the uploaded bytes carry no EXIF before sending them."""
    raw = base64.b64decode(uri.split(",", 1)[1])
    exif = Image.open(io.BytesIO(raw)).getexif()
    assert len(exif) == 0, "re-encoded upload still carries EXIF"
    print("upload_exif_stripped=True")


if __name__ == "__main__":
    main()
