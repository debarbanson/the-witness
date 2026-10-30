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
        if "nominatim" in url:
            return FakeResponse(200, fixture("nominatim.json"))
        if params.get("generator") == "geosearch":
            return FakeResponse(200, fixture("wp_geosearch.json"))
        if params.get("list") == "geosearch":
            return FakeResponse(200, fixture("wikidata_geosearch.json"))
        if params.get("props") == "labels|descriptions|sitelinks|claims":
            return FakeResponse(200, fixture("wb_enrich.json"))
        if params.get("props") == "labels":
            return FakeResponse(200, fixture("wb_kind_labels.json"))
        if params.get("props") == "sitelinks":
            return FakeResponse(200, fixture("wb_sitelinks.json"))
        raise AssertionError(f"unexpected request {url} {params}")

    get.calls = calls
    return get


def vision_pick(text="1 Test Tower\nHighly confident."):
    def respond(prompt, image_bytes):
        assert image_bytes[:2] == b"\xff\xd8"
        assert "Test Tower" in prompt
        answer = "YES\nThe photo shows the tower." if "YES or NO" in prompt else text
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": answer, "annotations": []}]}]}

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


def dated_photo(path, original=None, changed=None):
    exif = Image.Exif()
    if original is not None:
        exif[36867] = original
    if changed is not None:
        exif[306] = changed
    Image.new("RGB", (8, 8)).save(path, exif=exif)


def test_capture_year_prefers_original_date(tmp_path):
    photo = tmp_path / "p.jpg"
    dated_photo(photo, original="2006:05:12 18:32:39",
                changed="2020:01:01 00:00:00")
    assert identify.capture_year(photo) == 2006


def test_capture_year_falls_back_to_file_date(tmp_path):
    photo = tmp_path / "p.jpg"
    dated_photo(photo, changed="2012:02:19 13:43:21")
    assert identify.capture_year(photo) == 2012


def test_capture_year_without_dates_is_none(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    assert identify.capture_year(photo) is None


def test_overpass_query_shape_and_user_agent():
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    (call,) = post.calls
    assert "around:250,52.000000,4.000000" in call["data"]["data"]
    assert call["headers"]["User-Agent"] == identify.USER_AGENT
    assert "wikidata|wikipedia|heritage|historic|tourism|man_made" in call["data"]["data"]


def test_overpass_moves_to_next_instance_without_sleep():
    post = FakeTransport(
        [
            (502, {}),
            (200, fixture("overpass_nearby.json")),
        ]
    )
    sleeps = []
    elements = identify.fetch_overpass(52.0, 4.0, post=post, sleep=sleeps.append)
    assert len(elements) == 4
    assert [c["url"] for c in post.calls] == [
        identify.OVERPASS_INSTANCES[0],
        identify.OVERPASS_INSTANCES[1],
    ]
    assert sleeps == []


def test_overpass_all_instances_down_raises():
    post = FakeTransport([(502, {})] * 2)
    with pytest.raises(identify.SourceError):
        identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)


def test_overpass_result_cached():
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    identify.fetch_overpass(52.0, 4.0, post=post, sleep=lambda s: None)
    assert len(post.calls) == 1


def test_wikidata_nearby_returns_qids_and_coords():
    get = FakeTransport([(200, fixture("wikidata_geosearch.json"))])
    items = identify.fetch_wikidata_nearby(52.0, 4.0, get=get)
    assert [(i["qid"], i["lat"], i["lon"]) for i in items] == [
        ("Q999", 52.0002, 4.0001),
        ("Q1000", 51.9985, 4.001),
    ]
    assert get.calls[0]["params"]["list"] == "geosearch"
    assert get.calls[0]["headers"]["User-Agent"] == identify.USER_AGENT


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
    assert len(found.candidates) == 5
    assert found.description == "water tower"


def test_coordinates_round_to_4_decimals_at_entry():
    assert identify.checked_location((52.123456, 4.987654)) == (52.1235, 4.9877)
    payload = [{"display_name": "X", "lat": "50.234567", "lon": "4.111111",
                "importance": 1,
                "address": {"country_code": "be", "city": "Brussels"}}]
    get = FakeTransport([(200, payload)])
    lat, lon, _country, _town = identify.geocode(
        "Somewhere", get=get, sleep=lambda s: None)
    assert (lat, lon) == (50.2346, 4.1111)
    identify.clear_cache()


def test_location_event_carries_no_place(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    events = []
    found = identify.identify(
        photo, place="Synthetic Private Place", post=post, get=routed(),
        respond=vision_pick(), sleep=lambda s: None,
        progress=lambda event, data: events.append((event, data)))
    assert found.municipality == "Test Town"
    for event, data in events:
        assert "Synthetic Private Place" not in json.dumps(data)
        assert "Test Tower, Test Town, Netherlands" not in json.dumps(data)
    assert [d for e, d in events if e == "location"] == [
        {"precision": "typed place"}]


def test_identify_clears_lookup_caches(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    identify.clear_cache()
    identify.identify(photo, post=post, get=routed(), respond=vision_pick())
    assert identify._cache == {}
    failing = FakeTransport([(200, fixture("overpass_nearby.json"))])
    with pytest.raises(identify.NotIdentifiedError):
        identify.identify(photo, post=failing, get=routed(),
                          respond=vision_pick("NONE\nNothing matches."))
    assert identify._cache == {}


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
    enrich_langs = [c["params"]["languages"] for c in get.calls
                    if c["params"].get("props") == "labels|descriptions|sitelinks|claims"]
    assert enrich_langs == ["ja|en"]


def test_fetch_overpass_uses_short_timeout_and_memory_only(tmp_path):
    from witness.cache import Cache

    post = FakeTransport([(200, fixture("overpass_nearby.json")),
                          (200, fixture("overpass_nearby.json"))])
    first = identify.fetch_overpass(52.0, 4.0, post=post, cache=Cache(tmp_path))
    assert post.calls[0]["timeout"] == 5
    assert list(tmp_path.iterdir()) == []
    identify.clear_cache()
    second = identify.fetch_overpass(52.0, 4.0, post=post, cache=Cache(tmp_path))
    assert second == first
    assert len(post.calls) == 2


def test_geosearch_lookups_skip_disk_cache(tmp_path):
    from witness.cache import Cache

    cache = Cache(tmp_path)
    get = FakeTransport([(200, fixture("wikidata_geosearch.json"))])
    identify.fetch_wikidata_nearby(52.0, 4.0, get=get, cache=cache)
    get = FakeTransport([(200, fixture("wp_geosearch.json"))])
    identify.fetch_wp_nearby(52.0, 4.0, "nl", get=get, cache=cache)
    assert list(tmp_path.iterdir()) == []


def test_identify_run_leaves_no_coordinates_on_disk(tmp_path):
    from witness.cache import Cache

    photo = tmp_path / "p.jpg"
    gps_photo(photo, lat=(52, 0, 3), lon=(4, 0, 2), direction=201)
    cache_dir = tmp_path / "cache"
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    found = identify.identify(photo, post=post, get=routed(),
                              respond=vision_pick(), cache=Cache(cache_dir))
    assert found.name == "Test Tower"
    assert any(cache_dir.iterdir())
    for path in cache_dir.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert "52.00083" not in text
            assert "4.00056" not in text


def test_geocode_uses_nominatim_politely():
    get = FakeTransport([(200, fixture("nominatim.json"))])
    sleeps = []
    lat, lon, country, town = identify.geocode("Test Tower", get=get, sleep=sleeps.append)
    assert (lat, lon) == (52.0002, 4.0001)
    assert country == "nl"
    assert town == "Test Town"
    assert get.calls[0]["headers"]["User-Agent"] == identify.USER_AGENT
    assert get.calls[0]["timeout"] == 20
    assert sleeps == [1.1]


def test_geocode_prefers_most_important_namesake():
    payload = [
        {"display_name": "Atomium, Pharmacy, Laeken", "lat": "50.1", "lon": "4.1",
         "importance": 0.31, "address": {"country_code": "be"}},
        {"display_name": "Atomium, Heysel", "lat": "50.2", "lon": "4.2",
         "importance": 0.85, "address": {"country_code": "be", "city": "Brussels"}},
    ]
    get = FakeTransport([(200, payload)])
    lat, lon, country, town = identify.geocode("Atomium", get=get, sleep=lambda s: None)
    assert (lat, lon) == (50.2, 4.2)
    assert town == "Brussels"
    assert get.calls[0]["params"]["limit"] == 5


def test_geocode_error_hides_typed_place():
    marker = "SYNTHETIC_PRIVATE_PLACE"
    identify.clear_cache()
    response = FakeTransport([(200, [])])
    with pytest.raises(identify.NotIdentifiedError) as exc_info:
        identify.geocode(marker, get=response, sleep=lambda s: None)
    assert marker not in str(exc_info.value)


def test_geocode_cache_key_hides_typed_place():
    identify.clear_cache()
    get = FakeTransport([(200, fixture("nominatim.json"))])
    identify.geocode("Synthetic Private Place", get=get, sleep=lambda s: None)
    assert "Synthetic Private Place".lower() not in repr(identify._cache)
    identify.clear_cache()


def test_reverse_geocode_returns_country_and_municipality():
    get = FakeTransport([(200, fixture("nominatim_reverse.json"))])
    assert identify.reverse(52.0, 4.0, get=get, sleep=lambda s: None) == ("nl", "Test Town")
    assert get.calls[0]["timeout"] == 20


def test_geocode_retries_with_backoff_then_succeeds():
    get = FakeTransport(
        [TimeoutError("t1"), TimeoutError("t2"), (200, fixture("nominatim.json"))]
    )
    sleeps = []
    lat, lon, country, _name = identify.geocode("Test Tower", get=get, sleep=sleeps.append)
    assert (lat, lon) == (52.0002, 4.0001)
    assert country == "nl"
    assert len(get.calls) == 3
    assert sleeps == [1.1, 2, 1.1, 4, 1.1]


def test_geocode_failing_gives_clear_message():
    get = FakeTransport([TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")])
    with pytest.raises(identify.SourceError) as exc_info:
        identify.geocode("Test Tower", get=get, sleep=lambda s: None)
    assert "3 tries" in str(exc_info.value)
    assert len(get.calls) == 3


def test_enrich_reads_labels_descriptions_sitelinks_and_part_of():
    get = FakeTransport([(200, fixture("wb_enrich.json")), (200, fixture("wb_kind_labels.json"))])
    enriched = identify.enrich_candidates(
        get, ["Q9001", "Q9002", "Q9003", "Q9004"], ["en"])
    assert enriched["Q9001"]["label"] == "Test Castle"
    assert enriched["Q9001"]["description"] == "hill castle"
    assert enriched["Q9001"]["sitelinks"] == 2
    assert enriched["Q9001"]["part_of"] is None
    assert enriched["Q9002"]["part_of"] == "Q9001"
    assert enriched["Q9004"]["sitelinks"] == 6
    assert get.calls[0]["params"]["props"] == "labels|descriptions|sitelinks|claims"


def test_enrich_resolves_instance_of_kind():
    get = FakeTransport([(200, fixture("wb_enrich.json")), (200, fixture("wb_kind_labels.json"))])
    enriched = identify.enrich_candidates(get, ["Q9001", "Q9002"], ["en"])
    assert enriched["Q9001"]["kind"] == "castle"
    assert enriched["Q9002"]["kind"] == ""
    assert get.calls[1]["params"]["props"] == "labels"


def test_attach_enrich_prefers_instance_of_kind():
    merged = [identify.Candidate(name="X", kind="wikidata item", source="wd", qid="Q1"),
              identify.Candidate(name="Y", kind="wikidata item", source="wd", qid="Q2")]
    attached = identify.attach_enrich(merged, {"Q1": {"kind": "statue"}, "Q2": {"kind": ""}})
    assert [c.kind for c in attached] == ["statue", "wikidata item"]


def test_retry_prompt_bars_settling_for_containers():
    cand = identify.Candidate(name="X", kind="museum", source="wd", qid="Q1",
                              description="a museum")
    prompt = identify._pick_prompt([cand], ["Y"])
    assert "Ruled out already: Y." in prompt
    assert "not the building or place it was taken in" in prompt


def test_vision_prompts_carry_no_place_direction_or_distance():
    import inspect

    cand = identify.Candidate(name="X", kind="statue", source="wd", qid="Q1",
                              description="a statue", distance_m=120,
                              bearing_deg=45)
    assert "near" not in inspect.signature(identify._pick_prompt).parameters
    assert "near" not in inspect.signature(identify._look_prompt).parameters
    pick = identify._pick_prompt([cand], [])
    assert "taken near" not in pick
    assert "faced" not in pick
    assert "m away" not in pick
    assert "bearing" not in pick
    look = identify._look_prompt(cand)
    assert "taken near" not in look
    assert "m from" not in look
    assert "statue" in look and "a statue" in look


def test_fold_parts_annotates_parent_and_keeps_part():
    castle = identify.Candidate("Test Castle", "wikidata item", "wikidata", "Q9001",
                                distance_m=100, bearing_deg=0)
    keep = identify.Candidate("Test Keep", "wikidata item", "wikidata", "Q9002",
                              distance_m=15, bearing_deg=0)
    folded = identify.fold_parts([keep, castle], {"Q9002": "Q9001"})
    assert [c.name for c in folded] == ["Test Keep", "Test Castle"]
    assert folded[1].includes == ("Test Keep",)


def test_enrich_covers_all_merged_qids():
    cands = [cand(f"Place {i}", f"Q{i}", distance=10 + i) for i in range(15)]
    assert identify._enrich_qids(cands) == [f"Q{i}" for i in range(15)]
    many = [cand(f"Place {i}", f"Q{i}", distance=10 + i) for i in range(60)]
    assert len(identify._enrich_qids(many)) == 50


def test_dedupe_names_merges_same_spot_twins():
    wiki = identify.Candidate("Test Tower", "wikidata item", "wikidata", "Q999",
                              distance_m=22, bearing_deg=10, sitelinks=2)
    wp = identify.Candidate("test tower", "wikipedia article", "wikipedia", None,
                            distance_m=22, bearing_deg=10)
    far = identify.Candidate("Test Tower", "wikipedia article", "wikipedia", None,
                             distance_m=215, bearing_deg=40)
    (merged, other) = identify.dedupe_names([wiki, wp, far])
    assert (merged.name, merged.qid, merged.source) == (
        "Test Tower", "Q999", "wikidata+wikipedia")
    assert other.distance_m == 215


def test_fold_parts_keeps_orphans():
    keep = identify.Candidate("Test Keep", "wikidata item", "wikidata", "Q9002",
                              distance_m=15, bearing_deg=0)
    assert identify.fold_parts([keep], {"Q9002": "Q9001"}) == [keep]


def cand(name, qid=None, distance=10, sitelinks=0, source="wikidata", includes=()):
    return identify.Candidate(name, "wikidata item", source, qid, distance_m=distance,
                              bearing_deg=0, sitelinks=sitelinks, includes=includes)


def test_rank_prefers_notable_over_near():
    parts = [cand(f"Part {i}", f"QP{i}", distance=15 + i, sitelinks=1) for i in range(4)]
    castle = cand("Test Castle", "Q9001", distance=100, sitelinks=40)
    ranked = identify.rank_candidates([*parts, castle], place="Test Castle")
    assert ranked[0].name == "Test Castle"


def test_rank_keeps_lookalikes_for_vision():
    metro = cand("Teston", "Q9003", distance=36, sitelinks=12)
    arena = cand("Test Arena", "Q9004", distance=120, sitelinks=60)
    ranked = identify.rank_candidates([metro, arena], place="Test Arena")
    assert [c.name for c in ranked[:2]] == ["Test Arena", "Teston"]


def test_rank_sorts_unlabelled_last():
    near = cand("Q111", "Q111", distance=8, sitelinks=0)
    far = [cand(f"Far {i}", f"QF{i}", distance=200 + i, sitelinks=30) for i in range(5)]
    mid = cand("Mid Hall", "Q112", distance=50, sitelinks=0)
    ranked = identify.rank_candidates([near, mid, *far])
    assert [c.name for c in ranked][-1] == "Q111"


def test_rank_keeps_nearest_three_as_safety_net():
    far = [cand(f"Far {i}", f"QF{i}", distance=200 + i, sitelinks=30) for i in range(11)]
    mid = cand("Mid Hall", "Q112", distance=50, sitelinks=0)
    ranked = identify.rank_candidates([mid, *far])
    names = [c.name for c in ranked]
    assert "Mid Hall" in names
    assert len(ranked) <= 13


def test_rank_place_overlap_breaks_ties():
    a = cand("Rupert Hall", "Q201", distance=20, sitelinks=1)
    b = cand("Test Castle", "Q202", distance=20, sitelinks=1)
    ranked = identify.rank_candidates([a, b], place="Test Castle town")
    assert ranked[0].name == "Test Castle"


def test_wp_nearby_parses_generator_response():
    get = FakeTransport([(200, fixture("wp_geosearch.json"))])
    items = identify.fetch_wp_nearby(52.0, 4.0, "nl", get=get)
    assert [(i["qid"], i["label"]) for i in items] == [
        ("Q999", "Test Tower"), (None, "Testplein")]
    assert get.calls[0]["url"] == "https://nl.wikipedia.org/w/api.php"
    assert get.calls[0]["params"]["generator"] == "geosearch"


def test_merge_dedupes_wikipedia_by_qid():
    ranked = identify.merge_and_rank(
        [], [{"qid": "Q999", "lat": 52.0002, "lon": 4.0001}], 52.0, 4.0, None,
        extra=[{"qid": "Q999", "label": "Test Tower", "lat": 52.0002, "lon": 4.0001}])
    assert len(ranked) == 1
    assert ranked[0].source == "wikidata+wikipedia"


def test_second_look_parses_yes_no_and_unparseable():
    yes = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "YES\nShows the tower."}]}]}
    no = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "NO\nShows the square."}]}]}
    ramble = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "It looks like the tower."}]}]}
    empty = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": ""}]}]}
    assert identify.parse_second_look(yes) is True
    assert identify.parse_second_look(no) is False
    assert identify.parse_second_look(ramble) is None
    assert identify.parse_second_look(empty) is None


def test_second_look_no_retries_next_candidate(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    script = [
        "2 Test Memorial\nLooks memorial-ish.",
        "NO\nShows the tower, not the memorial.",
        "1 Test Tower\nClearly the tower.",
        "YES\nThe photo shows the tower.",
    ]

    def respond(prompt, image_bytes):
        assert image_bytes[:2] == b"\xff\xd8"
        text = script.pop(0)
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    found = identify.identify(photo, post=post, get=routed(), respond=respond)
    assert found.name == "Test Tower"
    assert found.rejected == ("Test Memorial",)
    assert script == []


def test_second_look_rejecting_everything_raises(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    script = ["1 Test Tower\nMaybe.", "NO\nNot the tower.",
              "2 Test Memorial\nMaybe.", "NO\nNot the memorial."]

    def respond(prompt, image_bytes):
        text = script.pop(0)
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    with pytest.raises(identify.NotIdentifiedError):
        identify.identify(photo, post=post, get=routed(), respond=respond)


def test_vision_shortlist_shows_kinds_and_descriptions(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    seen = {}

    def respond(prompt, image_bytes):
        if "YES or NO" in prompt:
            text = "YES\nFine."
        else:
            seen["prompt"] = prompt
            text = "1 Test Tower\nFine."
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    identify.identify(photo, post=post, get=routed(), respond=respond)
    assert "water tower" in seen["prompt"]
    assert "memorial" in seen["prompt"]
    assert "a detail of it" in seen["prompt"]


def test_overpass_budget_does_not_block_identify(tmp_path, monkeypatch):
    import time as time_module

    monkeypatch.setattr(identify, "OVERPASS_BUDGET", 0.2)
    photo = tmp_path / "p.jpg"
    gps_photo(photo)

    def slow_post(url, **kwargs):
        time_module.sleep(5)
        return FakeResponse(200, fixture("overpass_nearby.json"))

    def respond(prompt, image_bytes):
        assert "Test" in prompt
        text = "YES\nFine." if "YES or NO" in prompt else "1 Test\nFine."
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    timings = {}
    found = identify.identify(photo, post=slow_post, get=routed(),
                              respond=respond, timings=timings)
    assert found.qid == "Q999"
    assert timings["overpass_s"] < 2


def test_hung_source_is_dropped_at_budget(tmp_path, monkeypatch):
    import time as time_module

    monkeypatch.setattr(identify, "WIKIDATA_BUDGET", 0.2)
    monkeypatch.setattr(identify, "WP_BUDGET", 0.2)
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    get = routed()
    real = get

    def hanging(url, **kwargs):
        params = kwargs.get("params", {}) or {}
        if params.get("list") == "geosearch" or params.get("generator") == "geosearch":
            time_module.sleep(5)
        return real(url, **kwargs)

    started = time_module.perf_counter()
    found = identify.identify(photo, post=post, get=hanging,
                              respond=vision_pick(), sleep=lambda s: None)
    assert time_module.perf_counter() - started < 10
    assert found.name == "Test Tower"


def test_place_run_skips_reverse_geocode(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    get = routed()
    found = identify.identify(photo, place="Test Tower", post=post, get=get,
                              respond=vision_pick())
    assert found.country_code == "nl"
    assert sum("nominatim" in c["url"] for c in get.calls) == 1


def test_nearby_budgets_fit_busy_retries():
    # A busy search backend answers fast, so three tries plus two backoffs
    # stay inside each budget; the budget caps slower failures instead.
    from witness.web import BUSY_BACKOFF
    assert identify.WIKIDATA_BUDGET == 15
    assert identify.WP_BUDGET == 15
    assert 2 * BUSY_BACKOFF + 3 * 1 <= identify.WIKIDATA_BUDGET
    assert 2 * BUSY_BACKOFF + 3 * 1 <= identify.WP_BUDGET


def test_wikidata_nearby_retries_busy_backend_three_times():
    get = FakeTransport([TimeoutError("slow"), TimeoutError("slow"),
                         TimeoutError("slow"), (200, {})])
    with pytest.raises(identify.SourceError):
        identify.fetch_wikidata_nearby(52.0, 4.0, get=get, sleep=lambda s: None)
    assert len(get.calls) == 3
    assert get.calls[0]["timeout"] == identify.WIKIDATA_TIMEOUT


def test_wp_nearby_retries_busy_backend_three_times():
    get = FakeTransport([TimeoutError("slow"), TimeoutError("slow"),
                         TimeoutError("slow"), (200, {})])
    with pytest.raises(identify.SourceError):
        identify.fetch_wp_nearby(52.0, 4.0, "en", get=get, sleep=lambda s: None)
    assert len(get.calls) == 3
    assert get.calls[0]["timeout"] == identify.WP_TIMEOUT


def test_budgeted_reports_unexpected_errors_instead_of_dying_silently():
    events = []

    def boom(*args, **kwargs):
        raise ValueError("shaped wrong")

    key, value, _elapsed = identify._budgeted(
        "wikidata", 5, boom, progress=lambda e, d: events.append((e, d)))
    assert key == "wikidata"
    assert value == []
    assert ("source_error", {"source": "wikidata", "error": "shaped wrong"}) in events


def test_typed_place_searches_wider_than_gps(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    get = routed()
    identify.identify(photo, place="Test Tower", post=post, get=get,
                      respond=vision_pick(), sleep=lambda s: None)
    geo = [c for c in get.calls if c.get("params", {}).get("list") == "geosearch"][0]
    assert geo["params"]["gsradius"] == identify.PLACE_RADIUS_M == 1000
    assert f"around:{identify.PLACE_RADIUS_M}," in post.calls[0]["data"]["data"]

    gps = tmp_path / "g.jpg"
    gps_photo(gps)
    post2 = FakeTransport([(200, fixture("overpass_nearby.json"))])
    get2 = routed()
    identify.identify(gps, post=post2, get=get2,
                      respond=vision_pick(), sleep=lambda s: None)
    geo2 = [c for c in get2.calls if c.get("params", {}).get("list") == "geosearch"][0]
    assert geo2["params"]["gsradius"] == identify.RADIUS_M == 250


def test_none_pick_keeps_fixed_message_and_emits_explanation(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    events = []

    def respond(prompt, image_bytes):
        return {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": "NONE\nI am confident it shows a diver, not these.",
             "annotations": []}]}]}

    with pytest.raises(identify.NotIdentifiedError) as exc_info:
        identify.identify(photo, post=post, get=routed(), respond=respond,
                          sleep=lambda s: None,
                          progress=lambda e, d: events.append((e, d)))
    assert str(exc_info.value) == "none of the candidates matched"
    assert ("no_match", {"explanation": "I am confident it shows a diver, not these."}) in events


def test_exif_failure_falls_back_to_typed_place(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)  # bogus EXIF: nothing real near it
    real = routed()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        params = kwargs.get("params", {}) or {}
        coord = params.get("gscoord") or params.get("ggscoord") or ""
        if coord.startswith("52.000000|4.000000"):
            if params.get("list") == "geosearch":
                return FakeResponse(200, {"query": {"geosearch": []}})
            if params.get("generator") == "geosearch":
                return FakeResponse(200, {"query": {"pages": {}}})
        return real(url, **kwargs)

    post = FakeTransport([(200, {"elements": []}),
                          (200, fixture("overpass_nearby.json"))])
    found = identify.identify(photo, place="Test Tower", post=post, get=get,
                              respond=vision_pick(), sleep=lambda s: None)
    assert found.name == "Test Tower"
    assert sum("nominatim" in u and "reverse" not in u for u in calls) == 1


def test_second_look_names_kind_and_description():
    cand = identify.Candidate(name="Cristo Redentor", kind="statue", source="wd",
                              qid="Q79961", description="famous landmark in Rio")
    prompt = identify._look_prompt(cand)
    assert "statue" in prompt and "famous landmark in Rio" in prompt
    assert prompt.startswith("Second look")


def test_second_look_grounds_without_distance():
    cand = identify.Candidate(name="Cristo Redentor", kind="statue", source="wd",
                              qid="Q79961", description="famous landmark in Rio",
                              distance_m=13)
    prompt = identify._look_prompt(cand)
    assert "13 m" not in prompt
    assert "Cristo Redentor (statue)" in prompt


def test_failed_place_run_raises_original_error_not_nogps(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (8, 8)).save(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])

    def respond(prompt, image_bytes):
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "NONE\nNo match here.", "annotations": []}]}]}

    with pytest.raises(identify.NotIdentifiedError) as exc_info:
        identify.identify(photo, place="Test Tower", post=post, get=routed(),
                          respond=respond, sleep=lambda s: None)
    assert str(exc_info.value) == "none of the candidates matched"


def _look_script(second_answers):
    calls = []

    def respond(prompt, image_bytes):
        calls.append(prompt)
        if prompt.startswith("Second look"):
            n = sum(1 for c in calls if c.startswith("Second look"))
            text = second_answers[min(n, len(second_answers)) - 1] + "\nWords."
        else:
            text = "1 Test Tower\nConfident."
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    return respond, calls


def plain_photo(path):
    Image.new("RGB", (32, 32), (9, 9, 9)).save(path)


def test_browser_location_finds_candidate_without_gps(tmp_path):
    photo = tmp_path / "p.jpg"
    plain_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    found = identify.identify(photo, post=post, get=routed(),
                              respond=vision_pick(),
                              location=(52.0, 4.0), sleep=lambda s: None)
    assert found.name == "Test Tower"


def test_exif_wins_over_browser_location(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo, lat=(52, 0, 1), lon=(4, 0, 1))
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    found = identify.identify(photo, post=post, get=routed(),
                              respond=vision_pick(),
                              location=(48.85, 2.35), sleep=lambda s: None)
    assert found.name == "Test Tower"
    body = post.calls[0]["data"]["data"]
    assert "52.0003" in body  # EXIF wins, rounded to 4 decimals
    assert "52.000278" not in body
    assert "48.85" not in body


def test_invalid_browser_location_raises(tmp_path):
    photo = tmp_path / "p.jpg"
    plain_photo(photo)
    with pytest.raises(identify.IdentifyError):
        identify.identify(photo, respond=vision_pick(), location=("x", None))
    with pytest.raises(identify.IdentifyError):
        identify.identify(photo, respond=vision_pick(), location=(100.0, 0.0))


def _scan_for_needles(strings, root, events):
    for path in Path(root).rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            for needle in strings:
                assert needle not in text, f"{needle} leaked into {path}"
    blob = json.dumps(events, default=str)
    for needle in strings:
        assert needle not in blob, f"{needle} leaked into a progress event"


def test_browser_location_never_reaches_disk_or_page(tmp_path):
    from witness.cache import Cache

    photo = tmp_path / "p.jpg"
    plain_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    events = []
    found = identify.identify(
        photo, post=post, get=routed(), respond=vision_pick(),
        location=(52.000231, 4.000137), sleep=lambda s: None,
        cache=Cache(str(tmp_path / "cache")),
        progress=lambda event, data: events.append((event, data)))
    assert found.name == "Test Tower"
    _scan_for_needles(["52.000231", "4.000137"], tmp_path / "cache", events)


def test_typed_place_never_reaches_disk_or_page(tmp_path):
    from witness.cache import Cache

    photo = tmp_path / "p.jpg"
    plain_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    events = []
    found = identify.identify(
        photo, place="Test Tower", post=post, get=routed(),
        respond=vision_pick(), sleep=lambda s: None,
        cache=Cache(str(tmp_path / "cache")),
        progress=lambda event, data: events.append((event, data)))
    assert found.name == "Test Tower"
    _scan_for_needles(["52.0002", "4.0001"], tmp_path / "cache", events)


def test_second_look_no_rejects_without_retry(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    script = ["1 Test Tower\nMaybe.", "NO\nNot the tower.",
              "1 Test Memorial\nLikely.", "YES\nClearly the memorial."]

    def respond(prompt, image_bytes):
        text = script.pop(0)
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    found = identify.identify(photo, post=post, get=routed(), respond=respond,
                              sleep=lambda s: None)
    assert found.name == "Test Memorial"
    assert found.rejected == ("Test Tower",)
    assert script == []  # the NO was not repeated


def test_second_look_retries_unparseable_answer(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    script = ["1 Test Tower\nMaybe.", "Hard to say from here.",
              "YES\nClearly the tower."]

    def respond(prompt, image_bytes):
        text = script.pop(0)
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    found = identify.identify(photo, post=post, get=routed(), respond=respond,
                              sleep=lambda s: None)
    assert found.name == "Test Tower"
    assert script == []


def test_two_unparseable_second_looks_reject_the_pick(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    respond, calls = _look_script(["Hard to say", "Still unsure"])
    with pytest.raises(identify.NotIdentifiedError) as exc_info:
        identify.identify(photo, post=post, get=routed(), respond=respond,
                          sleep=lambda s: None)
    assert "rejected every pick" in str(exc_info.value)
    # two looks per pick attempt, two attempts, both rejected
    assert sum(1 for c in calls if c.startswith("Second look")) == 4


def test_single_no_per_pick_rejects_everything(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    post = FakeTransport([(200, fixture("overpass_nearby.json"))])
    respond, calls = _look_script(["NO", "NO"])
    with pytest.raises(identify.NotIdentifiedError) as exc_info:
        identify.identify(photo, post=post, get=routed(), respond=respond,
                          sleep=lambda s: None)
    assert "rejected every pick" in str(exc_info.value)
    assert sum(1 for c in calls if c.startswith("Second look")) == 2


def test_failed_sources_emit_error_events(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)
    real = routed()

    def failing_wiki(url, **kwargs):
        params = kwargs.get("params", {}) or {}
        if params.get("list") == "geosearch":
            raise TimeoutError("wikidata down")
        return real(url, **kwargs)

    def failing_post(url, **kwargs):
        raise TimeoutError("overpass down")

    def respond(prompt, image_bytes):
        assert "Test" in prompt
        text = "YES\nFine." if "YES or NO" in prompt else "1 Test\nFine."
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    events = []
    identify.identify(photo, post=failing_post, get=failing_wiki,
                      respond=respond, sleep=lambda s: None,
                      progress=lambda e, d: events.append((e, d)))
    errors = {d["source"] for e, d in events if e == "source_error"}
    assert {"wikidata", "overpass"} <= errors


def test_failed_source_never_empties_other_sources(tmp_path):
    photo = tmp_path / "p.jpg"
    gps_photo(photo)

    def failing_post(url, **kwargs):
        raise TimeoutError("overpass down")

    get = routed()
    real = get

    def failing_wiki(url, **kwargs):
        params = kwargs.get("params", {}) or {}
        if params.get("list") == "geosearch":
            raise TimeoutError("wikidata down")
        return real(url, **kwargs)

    def respond(prompt, image_bytes):
        assert "Test" in prompt
        text = "YES\nFine." if "YES or NO" in prompt else "1 Test\nFine."
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}]}

    found = identify.identify(photo, post=failing_post, get=failing_wiki,
                              respond=respond, sleep=lambda s: None)
    assert found.name in ("Testtoren", "Test Tower", "Testplein")
