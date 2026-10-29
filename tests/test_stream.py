"""Streaming film: opening card, scene events, buffer rule, speculation. No live calls."""

import threading
import time

from witness import stream


def test_opening_card_names_verified_year_only():
    card = stream.opening_card(
        "De Adriaan", "mill",
        [{"year": 1779, "anchor": "build"}, {"year": 1932}],
    )
    assert card["name"] == "De Adriaan"
    assert card["since_year"] == 1779
    assert card["text"] == "I have stood here since 1779."
    assert "photo" not in card


def test_opening_card_without_anchor_omits_the_year():
    card = stream.opening_card("Oak", "tree", [{"year": 1026}])
    assert card["since_year"] is None
    assert card["text"] is None
    assert card["name"] == "Oak"


def test_buffer_ready_when_build_fits_inside_play():
    # 6 scenes at 7 s: 42 s of film. 2 ready after 20 s (10 s each):
    # 4 left cost 40 s, inside 42 s of play.
    assert stream.buffer_ready(6, 2, 20.0, scene_seconds=7) is True
    # 1 ready after 20 s (20 s each): 5 left cost 100 s, beyond play.
    assert stream.buffer_ready(6, 1, 20.0, scene_seconds=7) is False
    assert stream.buffer_ready(6, 0, 20.0, scene_seconds=7) is False
    assert stream.buffer_ready(6, 6, 20.0, scene_seconds=7) is True


def test_scene_event_carries_number_year_caption_source_and_image():
    scene = {"from_year": 1932, "date_label": "1932",
             "state": {"condition": "ruin"},
             "caption_lines": [{"year": 1932, "line": "burnt down",
                                "url": "https://en.wikipedia.org/wiki/X"}]}
    event = stream.scene_event(2, scene, "out/x/scene-2.png", 45.5)
    assert event["event"] == "scene_ready"
    assert (event["scene"], event["year"]) == (2, 1932)
    assert event["caption_lines"][0]["url"] == "https://en.wikipedia.org/wiki/X"
    assert event["image"] == "out/x/scene-2.png"
    assert event["t"] == 45.5


def test_newly_ready_scenes_fire_once_when_their_claims_land():
    draft = [{"from_year": 1779}, {"from_year": 1932}, {"from_year": "today"}]
    to_check = [1779, 1779, 1932]
    assert stream.newly_ready_scenes(draft, [1779], to_check, set()) == []
    ready = stream.newly_ready_scenes(draft, [1779, 1779], to_check, set())
    assert [s["from_year"] for s in ready] == [1779]
    assert stream.newly_ready_scenes(draft, [1779, 1779], to_check, {1779}) == []
    ready = stream.newly_ready_scenes(draft, [1779, 1779, 1932], to_check, {1779})
    assert [s["from_year"] for s in ready] == [1932]


def test_speculation_starts_work_before_the_answer():
    started = threading.Event()

    def begin():
        started.set()
        time.sleep(0.2)
        return "research done"

    def decide():
        assert started.wait(timeout=5)  # work began before deciding
        return True

    confirmed, result = stream.confirm_speculative("Is this X?", begin, decide)
    assert (confirmed, result) == (True, "research done")


def test_declined_speculation_discards_the_result():
    begun = threading.Event()

    def begin():
        begun.set()
        time.sleep(0.2)
        return "thrown away"

    def decide():
        assert begun.wait(timeout=5)
        return False

    confirmed, result = stream.confirm_speculative("Is this X?", begin, decide)
    assert (confirmed, result) == (False, None)


def test_scene_numbers_follow_film_order_not_completion():
    draft = [{"from_year": 1779}, {"from_year": 1920}, {"from_year": "today"}]
    assert stream.scene_numbers(draft) == {1779: 1, 1920: 2, "today": 3}


def test_simulate_playback_no_pause_when_buffer_covers():
    ready = [("a", 10.0), ("b", 12.0), ("c", 14.0)]
    assert stream.simulate_playback(ready) == {"start": 10.0, "pauses": []}


def test_simulate_playback_names_stalled_scenes():
    ready = [("a", 10.0), ("b", 60.0), ("c", 61.0)]
    assert stream.simulate_playback(ready) == {"start": 10.0, "pauses": ["b", "c"]}


def test_simulate_playback_waits_when_nothing_ready_early():
    ready = [("a", 100.0), ("b", 101.0)]
    assert stream.simulate_playback(ready) == {"start": 101.0, "pauses": []}


def test_simulate_playback_empty_is_no_start():
    assert stream.simulate_playback([]) == {"start": None, "pauses": []}


def test_paint_shop_models_parallel_workers():
    verified = [("a", 0.0), ("b", 1.0), ("c", 2.0)]
    out = stream.simulate_paint_shop(verified, paint_seconds=10, workers=2)
    assert out == {"a": 10.0, "b": 11.0, "c": 20.0}


def test_paint_shop_single_worker_serialises():
    verified = [("a", 0.0), ("b", 5.0)]
    out = stream.simulate_paint_shop(verified, paint_seconds=10, workers=1)
    assert out == {"a": 10.0, "b": 20.0}


def test_simulate_playback_ignores_today_in_buffer_scan():
    ready = [("a", 100.0), ("b", 101.0), ("today", 0.0)]
    out = stream.simulate_playback(ready)
    assert out["pauses"] == []
    assert out["start"] == 101.0


def test_simulate_playback_scans_completion_order_not_film_order():
    ready = [("a", 10.0), ("b", 200.0), ("c", 12.0)]
    out = stream.simulate_playback(ready)
    assert out == {"start": 10.0, "pauses": ["b"]}
