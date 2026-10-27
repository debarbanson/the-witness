"""Step 0: identify the object in a photo from its location.

EXIF GPS (or a typed place via Nominatim) gives coordinates; Overpass and
Wikidata give nearby named candidates; rank by distance and let Muse Spark
pick from the photo. Coordinates are used for the lookups only and are
never stored or printed by this module.
"""

import io
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD

from witness.research import read_langs
from witness.web import USER_AGENT, WebError, mediawiki_get

RADIUS_M = 250
TOP_N = 5
OVERPASS_INSTANCES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_TRIES = 3
NOMINATIM_TIMEOUT = 20
NOMINATIM_BACKOFF = (2, 4)

QUERY = """[out:json][timeout:25];
nwr(around:{radius},{lat},{lon})[name][~"^(wikidata|wikipedia|heritage|historic|tourism|man_made)$"~"."];
out tags center;"""

_cache: dict = {}


class IdentifyError(Exception):
    """Base for step 0 failures."""


class NoGpsError(IdentifyError):
    """The photo carries no GPS data and no place was given."""


class NotIdentifiedError(IdentifyError):
    """No candidate matched the photo."""


class SourceError(IdentifyError):
    """A free source failed after retries."""


@dataclass(frozen=True)
class PhotoLocation:
    lat: float
    lon: float
    direction: int | None
    precision: str


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: str
    source: str
    qid: str | None
    articles: dict = field(default_factory=dict)
    distance_m: int = 0
    bearing_deg: int = 0


@dataclass(frozen=True)
class Identification:
    name: str
    kind: str
    qid: str | None
    articles: dict
    distance_m: int
    confidence: str
    candidates: tuple
    country_code: str | None = None


def clear_cache() -> None:
    _cache.clear()


def identify(photo, place=None, post=None, get=None, respond=None, sleep=time.sleep,
             cache=None, lang="en", timings=None, progress=None):
    """Run step 0. Transports and the vision call are injectable for tests.

    Reverse geocoding runs first (labels and articles need the country);
    then Overpass and Wikidata nearby in parallel, then sitelinks and the
    vision pick in parallel. Per-step seconds go into `timings` when given;
    `progress(event, data)` feeds the web page.
    """
    post = post or _post
    get = get or _get
    if respond is None:
        raise IdentifyError("a vision respond callable is required")
    steps = {} if timings is None else timings

    def emit(event, data=None):
        if progress is not None:
            progress(event, data or {})

    def guarded(key, default, func, *args, **kwargs):
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        except SourceError:
            return default
        finally:
            steps[f"{key}_s"] = round(time.perf_counter() - started, 1)

    try:
        location = read_location(photo)
    except NoGpsError:
        if not place:
            raise
        started = time.perf_counter()
        lat, lon = geocode(place, get=get, sleep=sleep)
        steps["geocode_s"] = round(time.perf_counter() - started, 1)
        location = PhotoLocation(lat=lat, lon=lon, direction=None, precision="typed place")
    lat, lon = location.lat, location.lon
    emit("location", {"precision": location.precision})
    country_code = guarded("reverse", None, reverse, lat, lon, get=get, sleep=sleep)
    order = read_langs(country_code, lang)
    with ThreadPoolExecutor(max_workers=2) as pool:
        osm_future = pool.submit(guarded, "overpass", [], fetch_overpass,
                                 lat, lon, post, sleep, cache)
        wiki_future = pool.submit(guarded, "wikidata", [], fetch_wikidata_nearby,
                                  lat, lon, get, sleep, cache, lang, country_code)
        osm, wiki = osm_future.result(), wiki_future.result()
    qids = [i["qid"] for i in wiki]
    qids += [t.get("wikidata") for el in osm for t in [el.get("tags", {})] if t.get("wikidata")]
    ranked = merge_and_rank(osm, wiki, lat, lon, location.direction)[:TOP_N]
    if not ranked:
        raise NotIdentifiedError("no named candidates near the photo")
    emit("candidates", {"count": len(ranked), "names": [c.name for c in ranked]})
    shortlist = "\n".join(
        f"{i + 1}. {c.name} ({c.kind}, about {c.distance_m} m away, "
        f"bearing {c.bearing_deg} degrees)"
        for i, c in enumerate(ranked)
    )
    facing = f" about {location.direction} degrees" if location.direction is not None else ""
    prompt = (
        f"The camera faced{facing}. Nearby known objects, nearest first:\n"
        f"{shortlist}\nWhich one does the photo show? Answer with its number "
        "and name first, then one sentence of confidence. If none of them, say NONE."
    )
    photo_bytes = _reencoded(photo)

    def vision():
        started = time.perf_counter()
        try:
            return parse_pick(respond(prompt, photo_bytes))
        finally:
            steps["vision_s"] = round(time.perf_counter() - started, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        articles_future = (
            pool.submit(guarded, "sitelinks", {}, fetch_sitelinks,
                        sorted(set(qids)), get, order, sleep, cache)
            if qids else None
        )
        pick = pool.submit(vision).result()
        articles = articles_future.result() if articles_future else {}
    if pick["none"]:
        raise NotIdentifiedError(pick.get("confidence") or "none of the candidates matched")
    number = pick.get("number")
    if number is None or not 1 <= number <= len(ranked):
        raise NotIdentifiedError(f"unparseable pick: {pick.get('name')}")
    chosen = ranked[number - 1]
    emit("pick", {"name": chosen.name})
    return Identification(
        name=chosen.name,
        kind=chosen.kind,
        qid=chosen.qid,
        articles=articles.get(chosen.qid, {}) if chosen.qid else {},
        distance_m=chosen.distance_m,
        confidence=pick.get("confidence", ""),
        candidates=tuple(ranked),
        country_code=country_code,
    )


def read_location(photo) -> PhotoLocation:
    tags = _gps_tags(photo)
    lat_ref, lon_ref = tags.get("GPSLatitudeRef"), tags.get("GPSLongitudeRef")
    lat_val, lon_val = tags.get("GPSLatitude"), tags.get("GPSLongitude")
    if not (lat_ref and lon_ref and lat_val and lon_val):
        raise NoGpsError("photo has no EXIF GPS; give --place instead")
    lat = _dms(lat_val, lat_ref)
    lon = _dms(lon_val, lon_ref)
    decimals = max(_decimals(lat_val[2]), _decimals(lon_val[2]))
    approx_m = 30 / (10**decimals) if decimals <= 4 else 0.01
    label = f"DMS to {decimals} dp, about {approx_m:g} m"
    direction = tags.get("GPSImgDirection")
    return PhotoLocation(
        lat=lat,
        lon=lon,
        direction=round(float(direction)) % 360 if direction is not None else None,
        precision=label,
    )


def _gps_tags(photo) -> dict:
    exif = Image.open(photo).getexif()
    gps_ifd = exif.get_ifd(IFD.GPSInfo) if hasattr(exif, "get_ifd") else {}
    return {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}


def _dms(value, ref) -> float:
    deg = float(value[0]) + float(value[1]) / 60 + float(value[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def _decimals(value) -> int:
    text = str(float(value))
    return len(text.split(".")[1]) if "." in text else 0


def _reencoded(photo) -> bytes:
    """JPEG bytes without EXIF, safe to upload."""
    img = Image.open(photo).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def fetch_overpass(lat, lon, post=None, sleep=time.sleep, cache=None) -> list:
    key = ("overpass", round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    cache_key = f"overpass:{lat:.5f},{lon:.5f}"
    if cache is not None:
        hit = cache.get(cache_key)
        if hit is not None:
            _cache[key] = hit
            return hit
    post = post or _post
    body = QUERY.format(radius=RADIUS_M, lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    last_error = ""
    for url in OVERPASS_INSTANCES:
        for attempt in (0, 1):
            try:
                resp = post(url, data={"data": body}, headers={"User-Agent": USER_AGENT}, timeout=30)
            except Exception as exc:  # noqa: BLE001 - any transport error moves on
                last_error = str(exc)[:120]
                break
            if resp.status_code in (429, 502):
                last_error = f"HTTP {resp.status_code} at {url}"
                if attempt == 0:
                    sleep(30)  # pause before retrying this instance
                continue
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            _cache[key] = elements
            if cache is not None:
                cache.put(cache_key, elements)
            return elements
    raise SourceError(f"Overpass failed on all instances ({last_error})")


def fetch_wikidata_nearby(lat, lon, get=None, sleep=time.sleep, cache=None, lang="en",
                          country_code=None) -> list:
    """Nearby items via geosearch on wikidata.org (WDQS avoided per pipeline)."""
    key = ("wd_nearby", round(lat, 5), round(lon, 5))
    if key in _cache:
        return _cache[key]
    get = get or _get
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat:.6f}|{lon:.6f}",
                "gsradius": RADIUS_M,
                "gsnamespace": 0,
                "gslimit": 50,
                "format": "json",
            },
            sleep=sleep,
            cache=cache,
        )
        labels = _wb_labels([r["title"] for r in data["query"]["geosearch"]], get, sleep, cache,
                            read_langs(country_code, lang))
    except WebError as exc:
        raise SourceError(str(exc))
    raw = data["query"]["geosearch"]
    items = [
        {"qid": r["title"], "label": labels.get(r["title"], r["title"]),
         "lat": r["lat"], "lon": r["lon"]}
        for r in raw
    ]
    _cache[key] = items
    return items


def _wb_labels(qids, get, sleep=time.sleep, cache=None, order=("en",)) -> dict:
    if not qids:
        return {}
    data = mediawiki_get(
        get,
        "https://www.wikidata.org/w/api.php",
        {
            "action": "wbgetentities",
            "ids": "|".join(qids[:50]),
            "props": "labels",
            "languages": "|".join(order),
            "format": "json",
        },
        sleep=sleep,
        cache=cache,
    )
    out = {}
    for qid, entity in data.get("entities", {}).items():
        lang_labels = entity.get("labels", {})
        best = None
        for code in dict.fromkeys([*order, *lang_labels]):
            if lang_labels.get(code):
                best = lang_labels[code]
                break
        out[qid] = best["value"] if best else qid
    return out


def fetch_sitelinks(qids, get=None, languages=("en",), sleep=time.sleep, cache=None) -> dict:
    if not qids:
        return {}
    get = get or _get
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "ids": "|".join(qids[:50]),
                "props": "sitelinks",
                "sitefilter": "|".join(f"{lang}wiki" for lang in languages),
                "format": "json",
            },
            sleep=sleep,
            cache=cache,
        )
    except WebError as exc:
        raise SourceError(str(exc))
    out = {}
    for qid, entity in data.get("entities", {}).items():
        links = entity.get("sitelinks", {})
        out[qid] = {
            lang: links[f"{lang}wiki"]["title"]
            for lang in languages
            if f"{lang}wiki" in links
        }
    return out


def merge_and_rank(osm, wiki, lat, lon, direction, radius=RADIUS_M) -> list:
    """Merge OSM and Wikidata candidates; drop past radius; nearest first."""
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
    for item in wiki:
        if item["qid"] in by_qid:
            if by_qid[item["qid"]]["source"] == "osm":
                by_qid[item["qid"]]["source"] = "osm+wikidata"
            continue
        by_qid[item["qid"]] = {
            "name": item.get("label") or item["qid"],
            "kind": "wikidata item",
            "source": "wikidata",
            "qid": item["qid"],
            "_lat": item["lat"],
            "_lon": item["lon"],
        }
    ranked = []
    for c in by_qid.values():
        distance = round(haversine(lat, lon, c["_lat"], c["_lon"]))
        if distance > radius:
            continue
        bearing = round(bearing_deg(lat, lon, c["_lat"], c["_lon"])) % 360
        ranked.append(
            Candidate(
                name=c["name"], kind=c["kind"], source=c["source"], qid=c["qid"],
                distance_m=distance, bearing_deg=bearing,
            )
        )
    if direction is None:
        ranked.sort(key=lambda c: c.distance_m)
    else:
        ranked.sort(key=lambda c: (c.distance_m, angular_diff(direction, c.bearing_deg)))
    return ranked


def parse_pick(response: dict) -> dict:
    """First line is 'N. name' or NONE; the rest is the confidence."""
    text = ""
    for item in response.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text = block.get("text", "")
    first, _, rest = text.strip().partition("\n")
    if first.strip().upper().startswith("NONE"):
        return {"none": True, "confidence": rest.strip()}
    number, _, name = first.partition(" ")
    number = number.rstrip(".")
    return {
        "none": False,
        "number": int(number) if number.isdigit() else None,
        "name": name.strip(),
        "confidence": rest.strip(),
    }


def geocode(place, get=None, sleep=time.sleep) -> tuple:
    """Nominatim fallback: typed place to coordinates, at most 1 req/s."""
    key = ("nominatim", place.strip().lower())
    if key in _cache:
        return _cache[key]
    results = _nominatim(
        NOMINATIM_URL, {"q": place, "format": "json", "limit": 1}, get, sleep
    )
    if not results:
        raise NotIdentifiedError(f"place not found: {place}")
    coords = (float(results[0]["lat"]), float(results[0]["lon"]))
    _cache[key] = coords
    return coords


def reverse(lat, lon, get=None, sleep=time.sleep) -> str | None:
    """Country code of coordinates, for the research reading order."""
    key = ("reverse", round(lat, 3), round(lon, 3))
    if key in _cache:
        return _cache[key]
    result = _nominatim(
        NOMINATIM_REVERSE_URL,
        {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "json"},
        get,
        sleep,
    )
    code = (result.get("address", {}) or {}).get("country_code")
    _cache[key] = code
    return code


def _nominatim(url, params, get, sleep):
    get = get or _get
    for attempt in range(NOMINATIM_TRIES):
        sleep(1.1)
        try:
            resp = get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=NOMINATIM_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - retried with backoff below
            if attempt < NOMINATIM_TRIES - 1:
                sleep(NOMINATIM_BACKOFF[attempt])
            else:
                raise SourceError(
                    "place lookup failed after 3 tries (network or proxy); "
                    "simplify --place or check the connection"
                ) from exc


def haversine(lat1, lon1, lat2, lon2) -> float:
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x))


def angular_diff(a: int, b: int) -> int:
    return abs((a - b + 180) % 360 - 180)


def _post(url, **kwargs):
    return requests.post(url, **kwargs)


def _get(url, **kwargs):
    return requests.get(url, **kwargs)
