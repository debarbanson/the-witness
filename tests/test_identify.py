"""Step 0: identify the object. No live calls; transports are faked."""

import json
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import IFD
from PIL.TiffImagePlugin import IFDRational

from witness import identify

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_cache():
    identify.clear_cache()
    yield
    identify.clear_cache()


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class FakeTransport:
    """Scripted fake for post/get. Each entry is (status, payload)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, payload = entry
        return FakeResponse(status, payload)


def routed(reverse_payload=None):
    """Fake get routing by request, for parallel lookups in any order."""
    calls = []

    def get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        params = kwargs.get("params", {}) or {}
        if "nominatim" in url and "reverse" in url:
            return FakeResponse(200, reverse_payload or fixture("nominatim_reverse.json"))
        if params.get("list") == "geosearch":
            return FakeResponse(200, fixture("wikidata_geosearch.json"))
        if params.get("props") == "labels":
            return FakeResponse(200, fixture("wb_labels.json"))
        if params.get("props") == "sitelinks":
            return FakeResponse(200, fixture("wb_sitelinks.json"))
        raise AssertionError(f"unexpected request {url} {params}")

    get.calls = calls
    return get


def vision_pick(text="1 Test Tower\nHighly confident."):
    def respond(prompt, image_bytes):
        assert image_bytes[:2] == b"\xff\xd8"
        assert "Test Tower" in prompt
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    return respond


def gps_photo(path, lat=(52, 0, 0), lon=(4, 0, 0), direction=None):
    exif = Image.Exif()
    gps = {
        1: "N",
        2: tuple(IFDRational(v, 1) for v in lat),
        3: "E",
        4: tuple(IFDRational(v, 1) for v in lon),
    }
    if direction is not None:
        gps[16] = "T"
        gps[17] = IFDRational(direction, 1)
    exif[IFD.GPSInfo] = gps
    Image.new("RGB", (32, 32), (9, 9, 9)).save(path, exif=exif)


def test_read_location_from_exif(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo, direction=201)
    loc = identify.read_location(photo)
    assert (loc.lat, loc.lon) == (52.0, 4.0)
    assert loc.direction == 201
    assert "2 dp" in loc.precision or "dp" in loc.precision


def test_read_location_without_gps_raises(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    with pytest.raises(identify.NoGpsError):
        identify.read_location(photo)


def test_overpass_query_shape_and_user_agent():
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    (call,) = post.calls
    assert "around:250,52.000000,4.000000" in call["data"]["data"]
    assert call["headers"]["User-Agent"] == identify.USER_AGENT
    assert "wikidata|wikipedia|heritage|historic|tourism|man_made" in call["data"]["data"]


def test_overpass_retries_then_second_instance():
    post = FakeTransport(
        [
            (502, {}),
            (502, {}),
            (200, fixture("overpass_nearby.json")),
        ]
    )
    sleeps = []
    elements = identify.fetch_overpass(52.0, 4.0, post=post, sleep=sleeps.append)
    assert len(elements) == 4
    assert [c["url"] for c in post.calls] == [
        identify.OVERPASS_INSTANCES[0],
        identify.OVERPASS_INSTANCES[0],
        identify.OVERPASS_INSTANCES[1],
    ]
    assert sleeps == [30]


def test_overpass_all_instances_down_raises():
    post = FakeTransport([(502, {})] * 4)
    with pytest.raises(identify.SourceError):
        identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)


def test_overpass_result_cached():
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    assert len(post.calls) == 1


def test_wikidata_nearby_merges_geosearch_and_labels():
    get = FakeTransport(
        [
            (200, fixture("wikidata_geosearch.json")),
            (200, fixture("wb_labels.json")),
        ]
    )
    items = identify.fetch_wikidata_nearby(52.0, 4.0, get=get, lang="nl")
    assert [(i["qid"], i["label"]) for i in items] == [
        ("Q999", "Testtoren"),
        ("Q1000", "Teststraat"),
    ]
    assert get.calls[0]["params"]["list"] == "geosearch"
    assert get.calls[0]["headers"]["User-Agent"] == identify.USER_AGENT


def test_wikidata_nearby_labels_follow_user_language():
    get = FakeTransport(
        [
            (200, fixture("wikidata_geosearch.json")),
            (200, fixture("wb_labels.json")),
        ]
    )
    items = identify.fetch_wikidata_nearby(52.0, 4.0, get=get, lang="en")
    assert [(i["qid"], i["label"]) for i in items] == [
        ("Q999", "Test Tower"),
        ("Q1000", "Test Street"),
    ]


def test_merge_drops_beyond_radius_and_ranks_by_distance():
    osm = fixture("overpass_nearby.json")["elements"]
    wiki = [
        {"qid": "Q999", "label": "Testtoren", "lat": 52.0002, "lon": 4.0001},
        {"qid": "Q1000", "label": "Teststraat", "lat": 51.9985, "lon": 4.001},
    ]
    ranked = identify.merge_and_rank(osm, wiki, 52.0, 4.0, direction=201)
    names = [c.name for c in ranked]
    assert "Test Municipality" not in names  # centre 1.1 km away
    assert names[0] == "Test Tower"  # nearest first, whatever the direction
    assert ranked[0].source == "osm+wikidata"
    assert all(c.distance_m <= identify.RADIUS_M for c in ranked)


def test_direction_breaks_distance_ties():
    osm = fixture("overpass_nearby.json")["elements"][:2]
    ranked = identify.merge_and_rank(osm, [], 52.0, 4.0, direction=195)
    # Memorial (bearing ~195) beats equidistant rivals; tower is nearest anyway.
    assert ranked[0].name == "Test Tower"


def test_vision_pick_parses_recorded_response():
    response = fixture("vision_pick.json")
    pick = identify.parse_pick(response)
    assert pick["none"] is False
    assert pick["number"] == 5
    assert "watertoren" in pick["name"].lower()


def test_vision_pick_none():
    pick = identify.parse_pick(fixture("vision_none.json"))
    assert pick["none"] is True


def test_identify_end_to_end_with_fakes(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo, direction=201)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    found = identify.identify(photo, post=post, get=routed(), respond=vision_pick())
    assert found.name == "Test Tower"
    assert found.qid == "Q999"
    assert found.articles == {"nl": "Testtoren", "en": "Test Tower"}
    assert found.country_code == "nl"
    assert len(found.candidates) == 4


def test_identify_none_raises_not_identified(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    with pytest.raises(identify.NotIdentifiedError):
        identify.identify(
            photo, post=post, get=routed(), respond=lambda p, b: fixture("vision_none.json")
        )


def test_identify_runs_overpass_and_wikidata_in_parallel(tmp_path):
    import threading

    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    barrier = threading.Barrier(2, timeout=10)

    def post(url, **kwargs):
        barrier.wait()
        return FakeResponse(200, fixture("overpass_nearby.json"))

    get = routed()

    def waiting_get(url, **kwargs):
        if (kwargs.get("params", {}) or {}).get("list") == "geosearch":
            barrier.wait()
        return get(url, **kwargs)

    found = identify.identify(photo, post=post, get=waiting_get, respond=vision_pick())
    assert found.name == "Test Tower"  # barrier passed: the lookups overlapped


def test_identify_times_each_step(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    timings = {}
    identify.identify(photo, post=post, get=routed(), respond=vision_pick(), timings=timings)
    assert {"reverse_s", "overpass_s", "wikidata_s", "sitelinks_s", "vision_s"} <= set(timings)
    assert all(v >= 0 for v in timings.values())


def test_identify_emits_progress_events(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    events = []
    identify.identify(photo, post=post, get=routed(), respond=vision_pick(),
                      progress=lambda event, data: events.append(event))
    assert events == ["location", "candidates", "pick"]


def test_identify_reads_local_languages_for_sitelinks_and_labels(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    get = routed({"address": {"country_code": "jp"}})
    found = identify.identify(photo, post=post, get=get, respond=vision_pick(), lang="en")
    assert found.country_code == "jp"
    sitefilter = [c["params"]["sitefilter"] for c in get.calls if c["params"].get("props") == "sitelinks"]
    assert sitefilter == ["jawiki|enwiki"]
    label_langs = [c["params"]["languages"] for c in get.calls if c["params"].get("props") == "labels"]
    assert label_langs == ["ja|en"]


def test_fetch_overpass_uses_short_timeout_and_disk_cache(tmp_path):
    from witness.cache import Cache

    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    first = identify.fetch_overpass(52.0, 4.0, post=post, cache=Cache(tmp_path))
    assert post.calls[0]["timeout"] == 30
    identify.clear_cache()
    second = identify.fetch_overpass(52.0, 4.0, post=post, cache=Cache(tmp_path))
    assert second == first
    assert len(post.calls) == 1


def test_geocode_uses_nominatim_politely():
    get = FakeTransport([(200, fixture("nominatim.json"))])
    sleeps = []
    lat, lon = identify.geocode("Test Tower", get=get, sleep=sleeps.append)
    assert (lat, lon) == (52.0002, 4.0001)
    assert get.calls[0]["headers"]["User-Agent"] == identify.USER_AGENT
    assert get.calls[0]["timeout"] == 20
    assert sleeps == [1.1]


def test_geocode_retries_with_backoff_then_succeeds():
    get = FakeTransport(
        [TimeoutError("t1"), TimeoutError("t2"), (200, fixture("nominatim.json"))]
    )
    sleeps = []
    lat, lon = identify.geocode("Test Tower", get=get, sleep=sleeps.append)
    assert (lat, lon) == (52.0002, 4.0001)
    assert len(get.calls) == 3
    assert sleeps == [1.1, 2, 1.1, 4, 1.1]


def test_geocode_failing_gives_clear_message():
    get = FakeTransport([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")])
    with pytest.raises(identify.SourceError) as exc_info:
        identify.geocode("Test Tower", get=get, sleep=lambda s: None)
    assert "3 tries" in str(exc_info.value)
    assert len(get.calls) == 3


def test_reverse_geocode_returns_country_code():
    get = FakeTransport([(200, fixture("nominatim_reverse.json"))])
    assert identify.reverse(52.0, 4.0, get=get, sleep=lambda s: None) == "nl"
    assert get.calls[0]["timeout"] == 20
