"""Step 0: identify the object in a photo from its location.

EXIF GPS (or a typed place via Nominatim) gives coordinates; Overpass and
Wikidata give nearby named candidates; rank by distance and let Muse Spark
pick from the photo. Coordinates are used for the lookups only and are
never stored or printed by this module.
"""

import hashlib
import io
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD

from witness.photo import ALLOWED_FORMATS, load_clean
from witness.research import read_langs
from witness.web import USER_AGENT, WebError, fetch_public, mediawiki_get, scrub_query

RADIUS_M = 250
PLACE_RADIUS_M = 1000  # a typed place is a fuzzy start; ranking sorts it out
TOP_N = 10
OVERPASS_BUDGET = 5
OVERPASS_TIMEOUT = 5
WIKIDATA_BUDGET = 15
WIKIDATA_TIMEOUT = 6
WP_BUDGET = 15
WP_TIMEOUT = 4
OVERPASS_INSTANCES = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
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
_LOOKUP_GEN = 0


def _stale(gen) -> bool:
    """A lookup thread is stale once a later lookup cleared the cache."""
    return gen is not None and gen != _LOOKUP_GEN


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
    description: str = ""
    sitelinks: int = 0
    includes: tuple = ()


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
    description: str = ""
    rejected: tuple = ()
    municipality: str | None = None


def clear_cache() -> None:
    global _LOOKUP_GEN
    _cache.clear()
    _LOOKUP_GEN += 1


def _budgeted(key, budget, func, *args, progress=None, **kwargs):
    """Run a source fetch with a hard budget; late answers are dropped
    and failures are reported, never silent."""
    box: dict = {}

    def job():
        started = time.perf_counter()
        try:
            box["value"] = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - reported, never silent
            box["value"] = []
            if progress is not None:
                progress("source_error", {"source": key, "error": scrub_query(str(exc))[:160]})
        finally:
            box["elapsed"] = round(time.perf_counter() - started, 1)

    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    thread.join(budget)
    if thread.is_alive() and progress is not None:
        progress("source_error", {"source": key,
                                  "error": f"no answer within {budget} s"})
    return key, box.get("value", []), box.get("elapsed", budget)


def checked_location(location) -> tuple:
    """Browser geolocation as floats, rounded to 4 decimals (about
    11 m: plenty for a 250 m lookup), or an error that names the rule."""
    try:
        lat, lon = float(location[0]), float(location[1])
    except (TypeError, ValueError, IndexError):
        raise IdentifyError("location must be two numbers (latitude, longitude)")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise IdentifyError("location is out of range")
    return round(lat, 4), round(lon, 4)


def identify(photo, place=None, post=None, get=None, respond=None, sleep=time.sleep,
             cache=None, lang="en", timings=None, progress=None, location=None):
    """Run step 0. Transports and the vision call are injectable for tests.

    EXIF GPS can lie (a placeholder far from the object), so when the
    GPS run matches nothing and a typed place was given, one retry runs
    from the place. The vision pick still gates it: no match, no film.
    Browser geolocation stands in only when the photo has no GPS; EXIF
    always wins, since it marks where the photo was taken.
    """
    if location is not None:
        location = checked_location(location)
    try:
        try:
            return _identify_once(photo, place=place, post=post, get=get, respond=respond,
                                  sleep=sleep, cache=cache, lang=lang, timings=timings,
                                  progress=progress, location=location)
        except NotIdentifiedError as failed:
            if not place:
                raise
            try:
                read_location(photo)
                had_precise = True
            except NoGpsError:
                had_precise = location is not None
            if not had_precise:
                raise failed
            if progress is not None:
                progress("fallback", {"to": "typed place"})
            return _identify_once(photo, place=place, post=post, get=get, respond=respond,
                                  sleep=sleep, cache=cache, lang=lang, timings=timings,
                                  progress=progress, _gps_ok=False, location=None)
    finally:
        clear_cache()


def _identify_once(photo, place=None, post=None, get=None, respond=None, sleep=time.sleep,
                   cache=None, lang="en", timings=None, progress=None, _gps_ok=True,
                   location=None):
    """One identify attempt: EXIF GPS first, then browser geolocation,
    then the typed place.

    Reverse geocoding runs first (labels and articles need the country);
    then Overpass and Wikidata nearby in parallel, then sitelinks and the
    vision pick in parallel. Per-step seconds go into `timings` when given;
    `progress(event, data)` feeds the web page.
    """
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
        except Exception as exc:  # noqa: BLE001 - one failing source never kills the film
            emit("source_error", {"source": key, "error": scrub_query(str(exc))[:160]})
            return default
        finally:
            steps[f"{key}_s"] = round(time.perf_counter() - started, 1)

    try:
        if not _gps_ok:
            raise NoGpsError("GPS ignored after the GPS run matched nothing")
        loc = read_location(photo)
        from_place = False
    except NoGpsError:
        if location is not None:
            lat, lon = location
            loc = PhotoLocation(lat=lat, lon=lon, direction=None,
                                precision="browser geolocation")
            from_place = False
            municipality = None
        else:
            if not place:
                raise
            started = time.perf_counter()
            lat, lon, country_code, municipality = geocode(place, get=get, sleep=sleep)
            steps["geocode_s"] = round(time.perf_counter() - started, 1)
            loc = PhotoLocation(lat=lat, lon=lon, direction=None, precision="typed place")
            from_place = True
    else:
        municipality = None
    location = loc
    lat, lon = location.lat, location.lon
    radius = PLACE_RADIUS_M if from_place else RADIUS_M
    emit("location", {"precision": location.precision})
    osm_box: dict = {}
    gen = _LOOKUP_GEN

    def overpass_job():
        started = time.perf_counter()
        try:
            osm_box["osm"] = fetch_overpass(lat, lon, post, sleep, cache, radius,
                                            gen=gen)
        except SourceError as exc:
            osm_box["osm"] = []
            emit("source_error", {"source": "overpass", "error": scrub_query(str(exc))[:160]})
        finally:
            osm_box["overpass_s"] = round(time.perf_counter() - started, 1)

    overpass_thread = threading.Thread(target=overpass_job, daemon=True)
    overpass_thread.start()
    if not from_place:
        country_code, municipality = guarded(
            "reverse", (None, None), reverse, lat, lon, get=get, sleep=sleep)
    order = read_langs(country_code, lang)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        wiki_future = pool.submit(_budgeted, "wikidata", WIKIDATA_BUDGET,
                                  fetch_wikidata_nearby, lat, lon, get, sleep, cache,
                                  radius, progress=progress, gen=gen)
        wp_future = pool.submit(_budgeted, "wpgeo", WP_BUDGET,
                                fetch_wp_nearby, lat, lon, order[0], get, sleep, cache,
                                radius, progress=progress, gen=gen)
        (_, wiki, wiki_s), (_, wpedia, wp_s) = wiki_future.result(), wp_future.result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    steps["wikidata_s"], steps["wpgeo_s"] = wiki_s, wp_s
    overpass_thread.join(OVERPASS_BUDGET)
    osm = osm_box.get("osm", [])
    steps["overpass_s"] = osm_box.get("overpass_s", OVERPASS_BUDGET)
    merged = merge_and_rank(osm, wiki, lat, lon, location.direction, radius=radius, extra=wpedia)
    if not merged:
        raise NotIdentifiedError("no named candidates near the photo")
    enriched = guarded("enrich", {}, enrich_candidates, get,
                       _enrich_qids(merged), order, sleep, cache)
    ranked = rank_candidates(
        fold_parts(dedupe_names(attach_enrich(merged, enriched)),
                   {qid: e["part_of"] for qid, e in enriched.items() if e["part_of"]}),
        place or "", location.direction)
    if not ranked:
        raise NotIdentifiedError("no named candidates near the photo")
    emit("candidates", {"count": len(ranked)})
    photo_bytes = _reencoded(photo)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        short_qids = sorted({c.qid for c in ranked if c.qid})
        articles_future = (
            pool.submit(guarded, "sitelinks", {}, fetch_sitelinks,
                        short_qids, get, order, sleep, cache)
            if short_qids else None
        )
        pool_cands = list(ranked)
        rejected: list = []
        chosen = None
        confidence = ""
        vision_elapsed = 0.0
        look_elapsed = 0.0
        try:
            for _ in range(2):
                started = time.perf_counter()
                pick = parse_pick(respond(_pick_prompt(pool_cands, rejected), photo_bytes))
                vision_elapsed += time.perf_counter() - started
                if pick["none"]:
                    emit("no_match", {"explanation": pick.get("confidence", "")})
                    raise NotIdentifiedError("none of the candidates matched")
                number = pick.get("number")
                if number is None or not 1 <= number <= len(pool_cands):
                    raise NotIdentifiedError(f"unparseable pick: {pick.get('name')}")
                candidate = pool_cands[number - 1]
                started = time.perf_counter()
                confirmed = parse_second_look(respond(_look_prompt(candidate), photo_bytes))
                if confirmed is None:
                    confirmed = parse_second_look(respond(_look_prompt(candidate), photo_bytes))
                    if confirmed is None:
                        confirmed = False  # twice unreadable is not a yes
                look_elapsed += time.perf_counter() - started
                if confirmed:
                    chosen, confidence = candidate, pick.get("confidence", "")
                    break
                rejected.append(candidate.name)
                del pool_cands[number - 1]
                if not pool_cands:
                    break
        except NotIdentifiedError:
            raise
        except Exception as exc:  # noqa: BLE001 - a dead model reads as no match
            raise NotIdentifiedError(f"vision pick failed: {exc}") from exc
        finally:
            steps["vision_s"] = round(vision_elapsed, 1)
            steps["second_look_s"] = round(look_elapsed, 1)
        articles = articles_future.result() if articles_future else {}
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if chosen is None:
        raise NotIdentifiedError("second look rejected every pick")
    return Identification(
        name=chosen.name,
        kind=chosen.kind,
        qid=chosen.qid,
        articles=articles.get(chosen.qid, {}) if chosen.qid else {},
        distance_m=chosen.distance_m,
        confidence=confidence,
        candidates=tuple(ranked),
        country_code=country_code,
        description=chosen.description,
        rejected=tuple(rejected),
        municipality=municipality,
    )


def read_location(photo) -> PhotoLocation:
    tags = _gps_tags(photo)
    lat_ref, lon_ref = tags.get("GPSLatitudeRef"), tags.get("GPSLongitudeRef")
    lat_val, lon_val = tags.get("GPSLatitude"), tags.get("GPSLongitude")
    if not (lat_ref and lon_ref and lat_val and lon_val):
        raise NoGpsError("photo has no EXIF GPS; give --place instead")
    lat = round(_dms(lat_val, lat_ref), 4)
    lon = round(_dms(lon_val, lon_ref), 4)
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


def _capture_stamp(photo):
    """The photo's EXIF date stamp parts, if it has one."""
    try:
        exif = Image.open(photo, formats=tuple(ALLOWED_FORMATS)).getexif()
    except (OSError, ValueError):
        return []
    for tag in (36867, 306):  # DateTimeOriginal, then DateTime
        stamped = exif.get(tag)
        if stamped:
            parts = str(stamped).split(":")
            try:
                int(parts[0])
            except (ValueError, IndexError):
                continue
            return parts
    return []


def capture_year(photo) -> int | None:
    """The photo's capture year from EXIF, if it has one."""
    try:
        return int(_capture_stamp(photo)[0])
    except (ValueError, IndexError):
        return None


def capture_month(photo) -> int | None:
    """The photo's capture month from EXIF, if it has one."""
    try:
        month = int(_capture_stamp(photo)[1])
    except (ValueError, IndexError):
        return None
    return month if 1 <= month <= 12 else None


def _gps_tags(photo) -> dict:
    try:
        exif = Image.open(photo, formats=tuple(ALLOWED_FORMATS)).getexif()
    except Exception:  # noqa: BLE001 - unreadable means no GPS, never a crash
        raise NoGpsError("photo has no EXIF GPS; give --place instead")
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
    img = load_clean(photo)
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def fetch_overpass(lat, lon, post=None, sleep=time.sleep, cache=None, radius=RADIUS_M,
                   gen=None) -> list:
    """Optional candidates: one fast try per instance, never a wait.

    The lookup key carries coordinates, so only the in-memory cache is
    used; `cache` is accepted and ignored. Same for the geosearch calls.
    A stale generation still returns its answer but never writes it.
    """
    key = ("overpass", round(lat, 5), round(lon, 5), radius)
    if key in _cache:
        return _cache[key]
    body = QUERY.format(radius=radius, lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    last_error = ""
    for url in OVERPASS_INSTANCES:
        try:
            fetched = fetch_public(
                url, sender=post, data={"data": body},
                headers={"User-Agent": USER_AGENT},
                timeout=OVERPASS_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - any transport error moves on
            last_error = scrub_query(str(exc))[:120]
            continue
        if fetched.status in (429, 502):
            last_error = f"HTTP {fetched.status} at {url}"
            continue
        if fetched.status >= 400:
            raise SourceError(f"Overpass refused ({fetched.status} at {url})")
        elements = json.loads(fetched.body.decode("utf-8")).get("elements", [])
        if not _stale(gen):
            _cache[key] = elements
        return elements
    raise SourceError(f"Overpass failed on all instances ({last_error})")


def fetch_wikidata_nearby(lat, lon, get=None, sleep=time.sleep, cache=None,
                        radius=RADIUS_M, gen=None) -> list:
    """Nearby items via geosearch on wikidata.org (WDQS avoided per pipeline).

    Labels come later from enrich_candidates, so one call failing never
    discards the coordinates.
    """
    key = ("wd_nearby", round(lat, 5), round(lon, 5), radius)
    if key in _cache:
        return _cache[key]
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat:.6f}|{lon:.6f}",
                "gsradius": radius,
                "gsnamespace": 0,
                "gslimit": 100,
                "format": "json",
            },
            sleep=sleep,
            timeout=WIKIDATA_TIMEOUT,
            cache=None,
            tries=3,
        )
    except WebError as exc:
        raise SourceError(str(exc))
    items = [
        {"qid": r["title"], "lat": r["lat"], "lon": r["lon"]}
        for r in data["query"]["geosearch"]
    ]
    if not _stale(gen):
        _cache[key] = items
    return items


def fetch_wp_nearby(lat, lon, lang, get=None, sleep=time.sleep, cache=None,
                  radius=RADIUS_M, gen=None) -> list:
    """Nearby articles via Wikipedia geosearch, independent of Overpass."""
    key = ("wp_nearby", lang, round(lat, 5), round(lon, 5), radius)
    if key in _cache:
        return _cache[key]
    try:
        data = mediawiki_get(
            get,
            f"https://{lang}.wikipedia.org/w/api.php",
            {
                "action": "query",
                "generator": "geosearch",
                "ggscoord": f"{lat:.6f}|{lon:.6f}",
                "ggsradius": radius,
                "ggslimit": 100,
                "prop": "coordinates|pageprops",
                "format": "json",
            },
            sleep=sleep,
            timeout=WP_TIMEOUT,
            cache=None,
            tries=3,
        )
    except WebError as exc:
        raise SourceError(str(exc))
    items = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        coords = (page.get("coordinates", {}) or [{}])[0]
        if "lat" not in coords or "lon" not in coords:
            continue
        items.append({
            "qid": (page.get("pageprops", {}) or {}).get("wikibase_item"),
            "label": page.get("title", ""),
            "lat": coords["lat"],
            "lon": coords["lon"],
        })
    if not _stale(gen):
        _cache[key] = items
    return items


def enrich_candidates(get, qids, order=("en",), sleep=time.sleep, cache=None) -> dict:
    """Labels, descriptions, sitelink counts and part-of parents, one call."""
    if not qids:
        return {}
    try:
        data = mediawiki_get(
            get,
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "ids": "|".join(qids[:50]),
                "props": "labels|descriptions|sitelinks|claims",
                "languages": "|".join(order),
                "format": "json",
            },
            sleep=sleep,
            cache=cache,
        )
    except WebError as exc:
        raise SourceError(str(exc))
    kinds = {}
    for qid, entity in data.get("entities", {}).items():
        for stmt in (entity.get("claims", {}) or {}).get("P31", []):
            value = ((stmt.get("mainsnak", {}) or {}).get("datavalue", {}) or {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                kinds[qid] = value["id"]
                break
    kind_labels = _kind_labels(get, sorted(set(kinds.values())), order, sleep, cache)
    out = {}
    for qid, entity in data.get("entities", {}).items():
        part_of = None
        for stmt in (entity.get("claims", {}) or {}).get("P361", []):
            value = ((stmt.get("mainsnak", {}) or {}).get("datavalue", {}) or {}).get("value", {})
            if isinstance(value, dict) and value.get("id"):
                part_of = value["id"]
                break
        out[qid] = {
            "label": _pick_text(entity.get("labels", {}), order) or qid,
            "description": _pick_text(entity.get("descriptions", {}), order) or "",
            "sitelinks": len(entity.get("sitelinks", {}) or {}),
            "part_of": part_of,
            "kind": kind_labels.get(kinds.get(qid, ""), ""),
        }
    return out


def _kind_labels(get, qids, order, sleep, cache) -> dict:
    """Instance-of labels for kinds, one batched call; {} when none."""
    if not qids:
        return {}
    try:
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
    except WebError as exc:
        raise SourceError(str(exc))
    return {
        qid: _pick_text(entity.get("labels", {}), order) or ""
        for qid, entity in data.get("entities", {}).items()
    }


def _pick_text(values: dict, order) -> str | None:
    """Label or description in reading order (local languages first)."""
    for code in dict.fromkeys([*order, *values]):
        if values.get(code):
            return values[code]["value"]
    return None


def fetch_sitelinks(qids, get=None, languages=("en",), sleep=time.sleep, cache=None) -> dict:
    if not qids:
        return {}
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


def merge_and_rank(osm, wiki, lat, lon, direction, radius=RADIUS_M, extra=()) -> list:
    """Merge OSM, Wikidata and Wikipedia candidates; drop past radius."""
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
    for item in extra:
        key = item.get("qid") or f"wp:{item.get('label')}"
        if key in by_qid:
            if "wikipedia" not in by_qid[key]["source"]:
                by_qid[key]["source"] += "+wikipedia"
            continue
        by_qid[key] = {
            "name": item.get("label") or key,
            "kind": "wikipedia article",
            "source": "wikipedia",
            "qid": item.get("qid"),
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


def attach_enrich(merged, enriched: dict) -> list:
    """Enriched names, descriptions and sitelink counts onto candidates.

    OSM's local name always wins; other candidates take the enriched
    label, falling back to the merged name."""
    out = []
    for c in merged:
        info = enriched.get(c.qid or "", {})
        name = c.name
        if c.qid and not c.source.startswith("osm"):
            name = info.get("label") or (c.name if c.name != c.qid else c.qid)
        out.append(replace(
            c, name=name, description=info.get("description", ""),
            sitelinks=info.get("sitelinks", 0),
            kind=info.get("kind") or c.kind))
    return out


def dedupe_names(cands) -> list:
    """Same name at the same spot from two sources is one candidate."""
    out = []
    for c in cands:
        if c.name.strip().lower() in ("(unnamed)", ""):
            out.append(c)
            continue
        twin = next(
            (o for o in out
             if o.name.strip().lower() == c.name.strip().lower()
             and o.distance_m == c.distance_m and o.bearing_deg == c.bearing_deg),
            None,
        )
        if twin is None:
            out.append(c)
            continue
        winner, loser = (c, twin) if _richer(c, twin) else (twin, c)
        source = winner.source
        for key in ("wikipedia", "wikidata", "osm"):
            if key in loser.source and key not in source:
                source += f"+{key}"
        out[out.index(twin)] = replace(
            winner, source=source, qid=winner.qid or loser.qid,
            description=winner.description or loser.description,
            sitelinks=max(winner.sitelinks, loser.sitelinks))
    return out


def _richer(first: Candidate, second: Candidate) -> bool:
    """Qid beats no qid; OSM detail beats plain entries; else first wins."""
    if bool(first.qid) != bool(second.qid):
        return bool(first.qid)
    if ("osm" in first.source) != ("osm" in second.source):
        return "osm" in first.source
    return True


def fold_parts(cands, parts: dict) -> list:
    """A part-of link (P361) annotates the parent and boosts it, but the
    part stays listed: the photo may show exactly the part."""
    by_qid = {c.qid: c for c in cands if c.qid}
    for c in cands:
        parent = parts.get(c.qid or "")
        if parent and parent in by_qid and parent != c.qid:
            by_qid[parent] = replace(
                by_qid[parent], includes=by_qid[parent].includes + (c.name,))
    return [by_qid.get(c.qid, c) if c.qid else c for c in cands]


def _enrich_qids(merged) -> list:
    """Every merged qid, up to the API's 50-per-call cap."""
    return [c.qid for c in merged if c.qid][:50]


def _notability_tier(sitelinks: int) -> int:
    if sitelinks >= 21:
        return 3
    if sitelinks >= 6:
        return 2
    if sitelinks >= 2:
        return 1
    return 0


def _name_overlap(place: str, name: str) -> int:
    place_tokens = set(re.findall(r"[a-z0-9]{3,}", place.lower()))
    name_tokens = set(re.findall(r"[a-z0-9]{3,}", name.lower()))
    return min(len(place_tokens & name_tokens), 2)


def _score(candidate: Candidate, place: str) -> int:
    if candidate.name == candidate.qid or candidate.name == "(unnamed)":
        return -10
    both = 1 if "+" in candidate.source else 0
    return (_notability_tier(candidate.sitelinks) + both
            + min(len(candidate.includes), 2) + _name_overlap(place, candidate.name))


def rank_candidates(cands, place="", direction=None, top_n=TOP_N) -> list:
    """Quality signals first (notability, agreement, folds, name match),
    distance and direction break ties; the nearest three are always kept."""
    def key(c):
        third = angular_diff(direction, c.bearing_deg) if direction is not None else 0
        return (-_score(c, place), c.distance_m, third)

    ordered = sorted(cands, key=key)
    shortlist = ordered[:top_n]
    named = [c for c in ordered if c.name != c.qid and c.name != "(unnamed)"]
    nearest_three = sorted(named, key=lambda c: c.distance_m)[:3]
    for c in nearest_three:
        if all(c is not s and (c.qid or c.name) != (s.qid or s.name) for s in shortlist):
            shortlist.append(c)
    return shortlist


def _shortlist_line(index: int, c: Candidate) -> str:
    bits = []
    if c.kind != "wikidata item":
        bits.append(c.kind.replace("_", " "))
    if c.description:
        bits.append(c.description)
    if c.includes:
        bits.append(f"includes {', '.join(c.includes)}")
    detail = f" ({'; '.join(bits)})" if bits else ""
    return f"{index}. {c.name}{detail}"


def _pick_prompt(pool, rejected) -> str:
    """Candidates by name, kind and description only: no place, no
    bearing, no distances. The photo decides, not the coordinates."""
    shortlist = "\n".join(_shortlist_line(i + 1, c) for i, c in enumerate(pool))
    ruled_out = (
        f"\nRuled out already: {', '.join(rejected)}. "
        "Pick only what the photo itself shows, not the building or place it was taken in."
        if rejected else ""
    )
    return (
        "Nearby known objects, best matches first:\n"
        f"{shortlist}{ruled_out}\nWhich one does the photo show? The photo may "
        "show the whole object or a detail of it. Answer with "
        "its number and name first, then one sentence of confidence. "
        "If none of them, say NONE."
    )


def _look_prompt(candidate: Candidate) -> str:
    """Second look at kind and description only: no place, no distance."""
    kind = candidate.kind.replace("_", " ")
    what = f"{candidate.name} ({kind})?"
    if candidate.description:
        what += f" It is described as: {candidate.description}."
    return (f"Second look at the same photo. Does it show {what} "
            "Answer YES or NO first, then one short sentence.")


def parse_second_look(response: dict) -> bool | None:
    """YES confirms the pick, NO rejects it, anything else is
    unparseable and earns one retry."""
    text = ""
    for item in response.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text = block.get("text", "")
    first = text.strip().split("\n")[0].strip().upper() if text.strip() else ""
    if first.startswith("YES"):
        return True
    if first.startswith("NO"):
        return False
    return None


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


def _municipality(address: dict) -> str | None:
    """The address's city, town, village or municipality, if any."""
    address = address or {}
    for key in ("city", "town", "village", "municipality"):
        if address.get(key):
            return address[key]
    return None


def geocode(place, get=None, sleep=time.sleep) -> tuple:
    """Nominatim fallback: typed place to rounded coordinates, country
    and municipality. Only the municipality travels on; the typed text
    and the full address never leave this call. The cache key is a
    hash, never the text.

    A name can belong to several places (a monument and a pharmacy),
    so the most important hit wins, not the first.
    """
    digest = hashlib.sha1(place.strip().lower().encode()).hexdigest()
    key = ("nominatim", digest)
    if key in _cache:
        return _cache[key]
    results = _nominatim(
        NOMINATIM_URL, {"q": place, "format": "json", "limit": 5,
                        "addressdetails": 1}, get, sleep
    )
    if not results:
        raise NotIdentifiedError("typed place matched nothing")
    first = max(results, key=lambda r: r.get("importance", 0))
    address = first.get("address", {}) or {}
    coords = (round(float(first["lat"]), 4), round(float(first["lon"]), 4),
              address.get("country_code"), _municipality(address))
    _cache[key] = coords
    return coords


def reverse(lat, lon, get=None, sleep=time.sleep) -> tuple:
    """Country code plus municipality of coordinates, for the research
    reading order and the canonical downstream identity."""
    key = ("reverse", round(lat, 3), round(lon, 3))
    if key in _cache:
        return _cache[key]
    result = _nominatim(
        NOMINATIM_REVERSE_URL,
        {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "json"},
        get,
        sleep,
    )
    address = result.get("address", {}) or {}
    found = (address.get("country_code"), _municipality(address))
    _cache[key] = found
    return found


def _nominatim(url, params, get, sleep):
    for attempt in range(NOMINATIM_TRIES):
        sleep(1.1)
        try:
            fetched = fetch_public(
                url, sender=get, params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=NOMINATIM_TIMEOUT, raise_status=True)
            return json.loads(fetched.body.decode("utf-8"))
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


