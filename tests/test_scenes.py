"""Step 3a: choose at most 7 scenes. Pure logic."""

from witness import scenes


def seg(year, to, state):
    return {"from_year": year, "to_year": to, "state": state}


def claim(year, text="stood here"):
    return {"year": year, "claim": text, "sources": ["https://example.com/x"]}


def test_small_timeline_keeps_every_state_change_plus_today():
    timeline = [seg(1779, 1932, "standing"), seg(1932, 2002, "burnt, only the base left")]
    chosen = scenes.choose_scenes(timeline, [claim(1779), claim(1932)])
    assert [(s["from_year"], s["state"]) for s in chosen] == [
        (1779, "standing"),
        (1932, "burnt, only the base left"),
        ("today", "today"),
    ]
    assert all(s["reason"] for s in chosen)


def test_many_states_capped_with_first_and_last_kept():
    timeline = [seg(1800 + i * 10, 1810 + i * 10, f"state-{i}") for i in range(10)]
    chosen = scenes.choose_scenes(timeline, [claim(1800 + i * 10) for i in range(10)])
    assert len(chosen) == 7
    assert chosen[0]["from_year"] == 1800
    assert chosen[-2]["from_year"] == 1890
    assert chosen[-1]["from_year"] == "today"


def test_strong_surroundings_period_gets_a_scene():
    timeline = [seg(1900, None, "standing")]
    claims = [claim(1900), claim(1950, "harbour busy"), claim(1950, "boats new")]
    chosen = scenes.choose_scenes(timeline, claims)
    years = [s["from_year"] for s in chosen]
    assert years == [1900, 1950, "today"]
    assert "surroundings" in chosen[1]["reason"]


def test_dropped_periods_become_caption_lines():
    timeline = [seg(1800 + i * 10, 1810 + i * 10, f"state-{i}") for i in range(10)]
    claims = [claim(1800 + i * 10, f"happened-{i}") for i in range(10)]
    chosen = scenes.choose_scenes(timeline, claims)
    lines = [line for s in chosen for line in s["caption_lines"]]
    assert len(lines) == 4  # 10 state years, 6 kept as scenes
    assert any("happened" in line["line"] for line in lines)
    # Each line sits on its nearest kept scene.
    for scene in chosen:
        for line in scene["caption_lines"]:
            assert abs(line["year"] - (scene["from_year"] or 0)) <= 20 or scene["from_year"] == "today"


def test_today_always_last_even_when_empty():
    assert scenes.choose_scenes([], [])[-1]["from_year"] == "today"
