"""Step 3a: choose at most 7 scenes. Pure logic."""

from witness import scenes


def state(condition="standing", description=""):
    return {"condition": condition, "degree": "total", "scope": "whole", "description": description}


def seg(year, to, condition="standing", description=""):
    return {"from_year": year, "to_year": to, "state": state(condition, description)}


def claim(year, text="stood here", date_text="", war_politics_only=False):
    return {"year": year, "claim": text, "date_text": date_text,
            "war_politics_only": war_politics_only, "sources": ["https://example.com/x"]}


def test_small_timeline_keeps_every_state_change_plus_today():
    timeline = [seg(1779, 1932, "standing"), seg(1932, 2002, "ruin", "burnt down")]
    chosen = scenes.choose_scenes(timeline, [claim(1779), claim(1932)])
    assert [(s["from_year"], s["state"]["condition"]) for s in chosen] == [
        (1779, "standing"),
        (1932, "ruin"),
        ("today", "standing"),
    ]
    assert all(s["reason"] for s in chosen)
    assert "ruin" in chosen[1]["reason"]


def test_many_states_capped_with_first_and_last_kept():
    timeline = [seg(1800 + i * 10, 1810 + i * 10, "standing", f"change-{i}") for i in range(10)]
    chosen = scenes.choose_scenes(timeline, [claim(1800 + i * 10) for i in range(10)])
    assert len(chosen) == 7
    assert chosen[0]["from_year"] == 1800
    assert chosen[-2]["from_year"] == 1890
    assert chosen[-1]["from_year"] == "today"


def test_strong_surroundings_period_gets_a_scene():
    timeline = [seg(1900, None)]
    claims = [claim(1900), claim(1950, "harbour busy"), claim(1950, "boats new")]
    chosen = scenes.choose_scenes(timeline, claims)
    years = [s["from_year"] for s in chosen]
    assert years == [1900, 1950, "today"]
    assert "surroundings" in chosen[1]["reason"]


def test_dropped_periods_become_caption_lines():
    timeline = [seg(1800 + i * 10, 1810 + i * 10, "standing", f"change-{i}") for i in range(10)]
    claims = [claim(1800 + i * 10, f"happened-{i}") for i in range(10)]
    chosen = scenes.choose_scenes(timeline, claims)
    lines = [line for s in chosen for line in s["caption_lines"]]
    assert len(lines) == 4  # 10 state years, 6 kept as scenes
    assert any("happened" in line["line"] for line in lines)
    # Each line sits on its nearest kept scene.
    for scene in chosen:
        for line in scene["caption_lines"]:
            assert abs(line["year"] - (scene["from_year"] or 0)) <= 20 or scene["from_year"] == "today"


def test_caption_lines_carry_their_source_url():
    timeline = [seg(1900, 1910)]
    tagged = claim(1950, "something happened", war_politics_only=True)
    tagged["url"] = "https://en.wikipedia.org/wiki/X"
    lines = [line for s in scenes.choose_scenes(timeline, [tagged])
             for line in s["caption_lines"]]
    assert lines[0]["url"] == "https://en.wikipedia.org/wiki/X"


def test_today_always_last_even_when_empty():
    assert scenes.choose_scenes([], [])[-1]["from_year"] == "today"


def test_war_politics_only_claims_are_captions_never_scenes():
    timeline = [seg(1900, None)]
    claims = [claim(1950, f"war-only claim {i}", war_politics_only=True) for i in range(3)]
    chosen = scenes.choose_scenes(timeline, claims)
    assert all(s["from_year"] != 1950 for s in chosen)
    lines = [line for s in chosen for line in s["caption_lines"]]
    assert any(line["year"] == 1950 for line in lines)


def test_caption_lines_prefer_vague_date_text():
    timeline = [seg(1900 + i * 10, 1910 + i * 10) for i in range(6)]
    claims = [claim(1900 + i * 10) for i in range(6)]
    claims.append(claim(1026, "built: thought to be 800 years old.", "about 800 years old"))
    lines = [line for s in scenes.choose_scenes(timeline, claims) for line in s["caption_lines"]]
    assert len(lines) == 1
    assert lines[0]["line"].startswith("about 800 years old")


def test_scenes_carry_date_label_and_flag():
    timeline = [seg(1026, 1908, "standing", "old tree")]
    timeline[0]["date_label"] = "about 800 to 1,200 years old"
    timeline[0]["flag"] = "implausible span"
    (first, today) = scenes.choose_scenes(timeline, [])
    assert first["date_label"] == "about 800 to 1,200 years old"
    assert first["flag"] == "implausible span"
    assert today["date_label"] == "today"


def test_surroundings_scenes_use_date_labels():
    timeline = [seg(1900, 1901), seg(1910, 1911)]
    claims = [claim(1920, "stood: the old tree stood here.", "between 800 and 1,200 years old")]
    (first, second, surroundings, today) = scenes.choose_scenes(timeline, claims)
    assert surroundings["date_label"] == "about 800 to 1,200 years old"


def test_same_claims_in_any_order_give_same_scenes():
    import json

    timeline = [seg(1900 + i * 10, 1910 + i * 10) for i in range(8)]
    claims = [claim(1900 + i * 10) for i in range(8)]
    claims.append(claim(1920, "zulu words stood here"))
    claims.append(claim(1920, "alpha words stood here"))
    first = scenes.choose_scenes(timeline, list(claims))
    second = scenes.choose_scenes(timeline, list(reversed(claims)))
    assert json.dumps(second, sort_keys=True) == json.dumps(first, sort_keys=True)


def test_mid_period_scene_drops_event_narrative():
    timeline = [{"from_year": 1899, "to_year": 2016,
                 "description_from": "detail",
                 "state": state("standing", "Construction began.")}]
    found = scenes._state_at(timeline, 1968)
    assert found["condition"] == "standing"
    assert found["description"] == ""
    assert scenes._state_at(timeline, 1899)["description"] == "Construction began."


def test_mid_period_scene_keeps_visible_condition():
    timeline = [{"from_year": 1970, "to_year": 1982,
                 "description_from": "visible_change",
                 "state": state("standing", "scaffolding supporting branches")}]
    found = scenes._state_at(timeline, 1975)
    assert found["description"] == "scaffolding supporting branches"


def test_mid_period_scene_without_provenance_drops_description():
    timeline = [seg(1899, 2016, "standing", "Construction began.")]
    found = scenes._state_at(timeline, 1968)
    assert found["description"] == ""
