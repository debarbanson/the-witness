"""Step 4: anchored era painting. Model calls are injected; no live calls."""

import base64

import pytest

from witness import paint


def scene(year=1850, condition="standing", description="The mill stands whole.",
          captions=()):
    return {"from_year": year, "date_label": str(year),
            "state": {"condition": condition, "degree": "total", "scope": "whole",
                      "description": description},
            "caption_lines": [{"year": year, "line": line} for line in captions]}


def test_scene_prompt_names_year_state_surroundings_and_framing():
    prompt = paint.scene_prompt(
        scene(1850, "standing", "The mill stands whole.",
              ["1850 caption: barges on the Spaarne."]),
        "De Adriaan", "Haarlem")
    assert "1850" in prompt
    assert "The mill stands whole" in prompt
    assert "barges on the Spaarne" in prompt
    assert "Haarlem" in prompt
    assert "same viewpoint" in prompt
    assert "not as it looks today" in prompt


def test_aftermath_retry_keeps_photo_without_predecessor():
    seen = []

    def call(prompt, prev, image):
        seen.append(image is not None)
        if len(seen) == 1:
            raise paint.PaintSafetyError("synthetic refusal")
        return {"image": b"fake", "response_id": "synthetic"}

    result = paint.paint_aftermath(call, lambda *a: "MATCHES", {
        "from_year": 1900, "state": {"condition": "burnt"}}, "Tower", "Town",
        photo_bytes=b"synthetic image")
    assert result["verdict"] == "matches"
    assert seen == [True, True]


def test_scene_prompt_without_municipality_reads_clean():
    prompt = paint.scene_prompt(
        scene(1850, "standing", "The mill stands whole."), "Mill", "")
    assert "in  in" not in prompt
    assert "1850" in prompt


def test_scene_prompt_states_partial_scope():
    prompt = paint.scene_prompt(
        scene(1932, "burnt", "Only the brick base is left.",
              ["1932 caption: the town watches."]),
        "De Adriaan", "Haarlem")
    assert "Only the brick base is left" in prompt
    assert "not as it looks today" in prompt


def test_extract_image_finds_generation_result():
    data = {"output": [
        {"type": "reasoning", "summary": []},
        {"type": "image_generation_call", "result": "aGVsbG8="},
    ]}
    assert paint.extract_image_b64(data) == "aGVsbG8="


def test_extract_image_none_when_absent():
    assert paint.extract_image_b64({"output": [{"type": "message"}]}) is None


def test_image_tools_match_proven_settings():
    assert paint.image_tools() == [
        {"type": "image_generation", "size": "1024x1536",
         "enable_image_search": False}]


def test_paint_chain_first_scene_carries_the_photo():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        return {"image": b"img", "response_id": f"r{len(seen)}"}

    results = paint.paint_chain(
        call, b"photo", [scene(1850), scene(1950)], "De Adriaan", "Haarlem")
    assert [r["response_id"] for r in results] == ["r1", "r2"]
    assert seen == [(None, b"photo"), ("r1", None)]
    assert results[0]["year"] == 1850


def test_paint_parallel_branches_every_era_from_first_scene():
    seen = []
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        prompts.append(prompt)
        if prev_id is None:
            return {"image": b"base", "response_id": "r-base"}
        return {"image": b"img", "response_id": "rx"}

    paint.paint_parallel(
        call, b"photo", [scene(1850), scene(1950)], "De Adriaan", "Haarlem")
    assert seen[0] == (None, b"photo")  # the first scene, not a spare turn
    assert "1850" in prompts[0]
    assert seen[1:] == [("r-base", None)]


def test_paint_parallel_marks_crashed_scene_dropped():
    def call(prompt, prev_id, photo_bytes=None):
        if prev_id is None:
            return {"image": b"base", "response_id": "r-base"}
        if "1950" in prompt:
            raise RuntimeError("timed out")
        return {"image": b"img", "response_id": "rx"}

    results = paint.paint_parallel(
        call, None, [scene(1850), scene(1950)], "Mill", "Town")
    assert [r["verdict"] for r in results] == ["unchecked", "dropped"]
    assert "timed out" in results[1]["note"]
    assert results[1]["year"] == 1950


def test_paint_parallel_base_crash_drops_all_scenes():
    def call(prompt, prev_id, photo_bytes=None):
        raise RuntimeError("down")

    results = paint.paint_parallel(
        call, None, [scene(1850), scene(1950)], "Mill", "Town")
    assert [r["verdict"] for r in results] == ["dropped", "dropped"]
    assert "down" in results[0]["note"]


def test_paint_parallel_dropped_base_regrounds_rest_on_photo():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        if prev_id is None and len(seen) == 1:
            raise RuntimeError("base down")
        return {"image": b"img", "response_id": "rx"}

    results = paint.paint_parallel(
        call, b"photo", [scene(1850), scene(1950)], "Mill", "Town")
    assert results[0]["verdict"] == "dropped"
    assert results[1]["verdict"] == "unchecked"
    assert seen[1] == (None, b"photo")


def test_paint_scene_check_crash_drops():
    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    def check(*args, **kwargs):
        raise RuntimeError("check down")

    result = paint.paint_scene(call, check, scene(1850), "Mill", "Town", "r0")
    assert result["verdict"] == "dropped"
    assert "check down" in result["note"]


def test_paint_chain_crash_drops_scene():
    def call(prompt, prev_id, photo_bytes=None):
        raise RuntimeError("down")

    results = paint.paint_chain(
        call, None, [scene(1850)], "Mill", "Town")
    assert results[0]["verdict"] == "dropped"
    assert "down" in results[0]["note"]


def test_paint_chain_crash_drops_one_scene_and_continues():
    def call(prompt, prev_id, photo_bytes=None):
        if "1850" in prompt:
            raise RuntimeError("boom")
        return {"image": b"img", "response_id": "r"}

    results = paint.paint_chain(
        call, None, [scene(1850), scene(1950)], "Mill", "Town")
    assert [r["verdict"] for r in results] == ["dropped", "unchecked"]


def test_paint_parallel_threads_base_id_to_rest():
    ids = iter(["r-base", "r2"])

    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": next(ids)}

    results = paint.paint_parallel(
        call, None, [scene(1850), scene(1950)], "De Adriaan", "Haarlem")
    assert [r["response_id"] for r in results] == ["r-base", "r2"]
    assert [r["year"] for r in results] == [1850, 1950]


def test_paint_scene_keeps_matching_painting():
    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES whole mill.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] == b"img"
    assert out["verdict"] == "matches"
    assert out["attempts"] == 1


def test_child_prompt_keeps_state_in_picture_book_style():
    made = scene(1850)
    adult = paint.scene_prompt(made, "Mill", "Town")
    child = paint.scene_prompt(made, "Mill", "Town", audience="child")
    assert "picture-book" in child
    assert "picture-book" not in adult
    assert "The object then: The Mill stands standing" in child
    assert "No text of any kind" in child


def test_child_prompt_shows_no_frightening_scene():
    burnt = scene(1932, condition="burnt", description="Only the base is left.")
    prompt = paint.scene_prompt(burnt, "Mill", "Town", audience="child")
    assert "no flames" in prompt and "no people in danger" in prompt
    calm = paint.scene_prompt(scene(1850), "Mill", "Town", audience="child")
    assert "no flames" not in calm
    adult = paint.scene_prompt(burnt, "Mill", "Town")
    assert "no flames" not in adult


def test_scene_caption_reads_the_audience_sentence():
    made = scene(1850)
    made["caption_sentence"] = {"text": "I opened my doors.",
                                "claim_year": 1850,
                                "claim_url": "https://a.example/x",
                                "child": {"text": "I opened long ago."}}
    assert paint.scene_caption(made) == "I opened my doors."
    assert paint.scene_caption(made, audience="child") == "I opened long ago."
    assert paint.scene_caption(scene(1850), audience="child") == ""


def test_paint_results_carry_the_checked_caption():
    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    made = scene(1850)
    made["caption_sentence"] = {"text": "I opened my doors.",
                                "claim_year": 1850,
                                "claim_url": "https://a.example/x"}
    out = paint.paint_scene(call, lambda image, p: "MATCHES whole mill.",
                            made, "Mill", "Town", "r0")
    assert out["caption"] == "I opened my doors."
    out = paint.paint_aftermath(call, lambda *a: "MATCHES",
                                made, "Mill", "Town")
    assert out["caption"] == "I opened my doors."
    bare = paint.paint_scene(call, lambda image, p: "MATCHES whole mill.",
                             scene(1850), "Mill", "Town", "r0")
    assert bare["caption"] == ""


def test_paint_scene_repaints_with_difference_then_keeps():
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        prompts.append(prompt)
        return {"image": b"img", "response_id": "r1"}

    answers = iter(["DIFFERS shows sails.", "MATCHES base only."])
    out = paint.paint_scene(call, lambda image, p: next(answers),
                            scene(1932, "burnt", "Only the base is left."),
                            "De Adriaan", "Haarlem", "r0")
    assert out["verdict"] == "matches"
    assert out["attempts"] == 2
    assert "shows sails" in prompts[1]


def test_paint_scene_drops_after_two_repaints():
    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "DIFFERS always.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] is None
    assert out["verdict"] == "dropped"
    assert out["attempts"] == 3


def test_paint_scene_skips_era_when_blocks_persist():
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        prompts.append(prompt)
        raise paint.PaintSafetyError("content_policy_violation")

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] is None
    assert out["verdict"] == "dropped"
    assert len(prompts) == 3


def test_contact_sheet_lays_images_side_by_side(tmp_path):
    from PIL import Image
    import io

    def png(color):
        buf = io.BytesIO()
        Image.new("RGB", (10, 20), color).save(buf, "PNG")
        return buf.getvalue()

    path = tmp_path / "sheet.png"
    paint.contact_sheet([("1850", png("red")), ("1950", png("blue"))], str(path))
    sheet = Image.open(path)
    assert sheet.size[0] == 20  # two 10 px panels
    assert sheet.size[1] > 20  # plus the label strip


def test_is_safety_block_matches_policy_wordings():
    assert paint.is_safety_block("400 content_policy_violation")
    assert paint.is_safety_block(
        "400 - The response was filtered due to the prompt triggering "
        "our content management policy.")
    assert not paint.is_safety_block("500 internal error")
    assert not paint.is_safety_block("unknown parameter: seed")


def test_paint_scene_retries_model_error_once_then_drops():
    calls = []

    def call(prompt, prev_id, photo_bytes=None):
        calls.append(prompt)
        if len(calls) < 2:
            raise paint.PaintError("500 internal error")
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] == b"img"
    assert out["attempts"] == 2


def test_paint_scene_drops_era_on_repeated_model_error():
    def call(prompt, prev_id, photo_bytes=None):
        raise paint.PaintError("500 internal error")

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] is None
    assert out["verdict"] == "dropped"
    assert "500" in out["note"]


def test_describe_state_frames_destroyed_as_remains():
    assert paint.describe_state(
        "De Adriaan",
        {"condition": "burnt", "degree": "partial", "scope": "whole",
         "description": "Only the brick base is left."}) == (
        "Only the remains of De Adriaan stand: Only the brick base is left.")
    assert paint.describe_state(
        "Mill",
        {"condition": "ruin", "degree": "total", "scope": "whole",
         "description": "Bare walls."}).startswith("Only the remains")


def test_describe_state_words_partial_scope_plainly():
    assert paint.describe_state(
        "Tower",
        {"condition": "damaged", "degree": "partial", "scope": "part",
         "description": "One wing scorched."}) == (
        "Part of Tower is damaged: One wing scorched.")
    assert paint.describe_state(
        "Mill",
        {"condition": "standing", "degree": "total", "scope": "whole",
         "description": ""}) == "The Mill stands whole."


def test_paint_scene_retries_safety_block_same_prompt_first():
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        prompts.append(prompt)
        if len(prompts) < 2:
            raise paint.PaintSafetyError("content management policy")
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1932, "burnt", "Base left."),
                            "De Adriaan", "Haarlem", "r0")
    assert out["image"] == b"img"
    assert prompts[0] == prompts[1]


def test_paint_scene_softens_only_after_second_block():
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        prompts.append(prompt)
        if len(prompts) < 3:
            raise paint.PaintSafetyError("content management policy")
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1932, "burnt", "Base left."),
                            "De Adriaan", "Haarlem", "r0")
    assert out["image"] == b"img"
    assert prompts[0] == prompts[1]
    assert "non-graphic" in prompts[2]


def test_paint_scene_drops_after_third_block():
    def call(prompt, prev_id, photo_bytes=None):
        raise paint.PaintSafetyError("content management policy")

    out = paint.paint_scene(call, lambda image, p: "MATCHES.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] is None
    assert out["verdict"] == "dropped"


def test_paint_scene_sends_photo_only_on_first_attempt():
    photos = []

    def call(prompt, prev_id, photo_bytes=None):
        photos.append(photo_bytes)
        return {"image": b"img", "response_id": "r1"}

    answers = iter(["DIFFERS sails wrong.", "MATCHES base only."])
    paint.paint_scene(call, lambda image, p: next(answers),
                      scene(1850), "Mill", "Town", None, photo_bytes=b"ph")
    assert photos == [b"ph", None]


def test_scene_prompt_drops_harm_lines_keeps_visible_ones():
    prompt = paint.scene_prompt(
        scene(1982, "standing", "floodlights added.",
              ["June 1981 damaged: cables snapped, injuring a pedestrian who later died.",
               "1986 restored: cables replaced by Bethlehem Steel."]),
        "Brooklyn Bridge", "New York")
    assert "later died" not in prompt
    assert "injuring" not in prompt
    assert "cables replaced" in prompt


def test_scene_prompt_falls_back_when_all_lines_harmful():
    prompt = paint.scene_prompt(
        scene(1982, "standing", "floodlights added.",
              ["1981 damaged: a pedestrian died."]),
        "Brooklyn Bridge", "New York")
    assert "died" not in prompt
    assert "everyday life" in prompt


def test_harm_filter_keeps_mortar_skilled_and_mortal():
    prompt = paint.scene_prompt(
        scene(1870, "standing", "masonry finished.",
              ["1870 note: skilled masons laid brick and mortar."]),
        "Bridge", "Town")
    assert "mortar" in prompt


def test_scene_prompt_bans_all_lettering():
    prompt = paint.scene_prompt(scene(1850), "Mill", "Town")
    assert "No text" in prompt
    assert "signs" in prompt and "dates" in prompt


def test_paint_scene_crash_retry_keeps_photo_without_predecessor():
    seen = []
    calls = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("timed out")
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES whole.",
                            scene(1850, "standing", "The mill stands whole."),
                            "De Adriaan", "Haarlem", None, photo_bytes=b"photo")
    assert out["verdict"] == "matches"
    assert seen == [(None, b"photo"), (None, b"photo")]


def test_paint_scene_crash_retry_chains_when_predecessor_exists():
    seen = []
    calls = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("timed out")
        return {"image": b"img", "response_id": "r2"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES whole.",
                            scene(1950, "standing", "The mill stands whole."),
                            "De Adriaan", "Haarlem", "r1", photo_bytes=b"photo")
    assert out["verdict"] == "matches"
    assert seen == [("r1", None), ("r1", None)]


def test_paint_scene_repaint_keeps_claims_in_prompt():
    prompts = []

    def call(prompt, prev_id, photo_bytes=None):
        prompts.append(prompt)
        return {"image": b"img", "response_id": "r1"}

    answers = iter(["DIFFERS shows sails.", "MATCHES base only."])
    out = paint.paint_scene(call, lambda image, p: next(answers),
                            scene(1850, "standing", "The mill stands whole."),
                            "De Adriaan", "Haarlem", "r0",
                            claims=[vclaim(1850, "barges unload grain at the quay")])
    assert out["verdict"] == "matches"
    assert "barges unload grain" in prompts[0]
    assert "barges unload grain" in prompts[1]


def test_scene_prompt_adds_season_sentence():
    prompt = paint.scene_prompt(scene(1850), "Mill", "Town", season="summer")
    assert "summer" in prompt
    assert "no snow" in prompt


def test_scene_prompt_skips_season_when_state_governs_canopy():
    prompt = paint.scene_prompt(
        scene(2026, "standing", "canopy leafless, no leaves produced."),
        "Oak", "Forest", season="summer")
    assert "summer" not in prompt
    assert "leafless" in prompt


def test_scene_prompt_lists_excluded_anchor_elements():
    prompt = paint.scene_prompt(scene(1932), "Tower", "Town",
                                excluded=["tulip banners", "snow"])
    assert "tulip banners" in prompt
    assert "Do not show" in prompt


def test_anchor_report_parses_season_and_elements():
    report = paint.anchor_report(
        lambda photo, prompt: "Season: winter\nsnow on the ground\nparagliders\nmodern cars",
        b"photo")
    assert report == {"season": "winter",
                      "elements": ["snow on the ground", "paragliders", "modern cars"]}


def test_anchor_report_unparseable_season_is_none():
    report = paint.anchor_report(lambda photo, prompt: "no idea\ntulip banners",
                                 b"photo")
    assert report == {"season": None, "elements": ["tulip banners"]}


def test_element_allowed_needs_every_word_mentioned():
    assert paint.element_allowed("tulip banners", ["tulip banners added"]) is True
    assert paint.element_allowed("modern cars", ["vintage cars pass"]) is False
    assert paint.element_allowed("snow", ["no mention here"]) is False


def test_excluded_elements_persist_once_verified():
    dated = [(1986, "tulip banners added"), (1991, "shop opened")]
    assert paint.excluded_elements(["tulip banners", "paragliders"], dated, 1932) == [
        "tulip banners", "paragliders"]
    assert paint.excluded_elements(["tulip banners", "paragliders"], dated, 1991) == [
        "paragliders"]


def test_paint_directives_combines_season_and_exclusions():
    out = paint.paint_directives(
        lambda photo, prompt: "Season: summer\ntulip banners",
        b"photo", [(1932, "built plain"), (1986, "tulip banners added")])
    assert out["season"] == "summer"
    assert out["excluded"] == {1932: ["tulip banners"], 1986: []}


def test_paint_scene_passes_caption_to_check():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    def ask(image, prompt):
        seen.append(prompt)
        return "MATCHES agree."

    made = scene(1999, "under_construction", "Foundations open.")
    made["caption_sentence"] = {"text": "My first pile was put in the ground.",
                                "claim_year": 1999, "claim_url": "u"}
    paint.paint_scene(call, ask, made, "De Adriaan", "Haarlem", "r0")
    assert "My first pile was put in the ground." in seen[0]


def test_recover_scene_ignores_non_critical_states():
    calls = []
    out = paint.recover_scene(
        lambda image, p: calls.append(p) or "MATCHES.",
        scene(1850), "De Adriaan", [("old", b"img")])
    assert out is None
    assert calls == []


def test_recover_scene_keeps_newest_passing_painting():
    answers = iter(["DIFFERS text dated.", "MATCHES base only."])
    out = paint.recover_scene(
        lambda image, p: next(answers),
        scene(1932, "ruin", "Only stones and beams left."),
        "De Adriaan", [("b1", b"new"), ("parallel", b"old")])
    assert out["image"] == b"old"
    assert out["source"] == "parallel"


def test_recover_scene_returns_none_when_nothing_passes():
    out = paint.recover_scene(
        lambda image, p: "DIFFERS text dated.",
        scene(1932, "ruin", "Only stones and beams left."),
        "De Adriaan", [("b1", b"new")])
    assert out is None


def test_aftermath_prompt_frames_a_calm_next_day():
    prompt = paint.aftermath_prompt(
        scene(1932, "ruin", "Only stones and burned beams left.",
              ["1932 burnt: the fire brigade could not save the mill."]),
        "De Adriaan", "Haarlem")
    assert "Only the remains of De Adriaan stand" in prompt
    assert "morning after" in prompt
    assert "no flames" in prompt
    assert "no people in distress" in prompt
    assert "fire brigade" not in prompt


def test_paint_aftermath_keeps_a_matching_calm_scene():
    def call(prompt, prev_id, photo_bytes=None):
        assert "morning after" in prompt
        return {"image": b"img", "response_id": "r9"}

    out = paint.paint_aftermath(
        call, lambda image, p: "MATCHES calm remains.",
        scene(1932, "ruin", "Only stones left."), "De Adriaan", "Haarlem")
    assert out["verdict"] == "matches"
    assert out["image"] == b"img"


def test_paint_aftermath_drops_after_two_blocks():
    def call(prompt, prev_id, photo_bytes=None):
        raise paint.PaintSafetyError("content_policy_violation")

    out = paint.paint_aftermath(
        call, lambda image, p: "MATCHES.",
        scene(1932, "ruin", "Only stones left."), "De Adriaan", "Haarlem")
    assert out["verdict"] == "dropped"
    assert out["image"] is None


def vclaim(year, text, verdict="supported"):
    return {"year": year, "url": "https://example.com/x", "verdict": verdict,
            "claim": text, "rewritten": None, "quote": "q"}


def test_scene_prompt_uses_own_claims_when_no_caption_lines():
    prompt = paint.scene_prompt(
        scene(2002, "standing", "The lighthouse stands whole."),
        "Rubjerg Knude Fyr", "Rubjerg Knude",
        claims=[vclaim(2002, "abandoned: Museum abandoned in 2002 due to shifting sands.")])
    assert "shifting sands" in prompt


def test_scene_prompt_prefers_caption_lines_over_claims():
    prompt = paint.scene_prompt(
        scene(2002, "standing", "Whole.", ["harbour busy"]),
        "Rubjerg Knude Fyr", "Rubjerg Knude",
        claims=[vclaim(2002, "abandoned due to shifting sands")])
    assert "harbour busy" in prompt
    assert "shifting sands" not in prompt


def test_scene_prompt_skips_harm_other_year_and_unverified_claims():
    prompt = paint.scene_prompt(
        scene(2002, "standing", "Whole."), "Rubjerg Knude Fyr", "Rubjerg Knude",
        claims=[vclaim(2002, "died: The keeper died in the storm."),
                vclaim(1968, "sand drift blinded the light"),
                vclaim(2002, "dunes grew tall", verdict="unsupported")])
    assert "died" not in prompt
    assert "sand drift" not in prompt
    assert "dunes grew" not in prompt
    assert "everyday life" in prompt


def test_paint_parallel_forwards_claims_to_scenes():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append(prompt)
        return {"image": b"img", "response_id": "r1"}

    paint.paint_parallel(
        call, lambda image, p: "MATCHES.", [scene(2002)], "Fyr", "Knude",
        claims=[vclaim(2002, "abandoned due to shifting sands")])
    assert any("shifting sands" in prompt for prompt in seen)
