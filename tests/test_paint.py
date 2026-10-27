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


def test_paint_chain_threads_previous_ids_in_order():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append((prev_id, photo_bytes))
        return {"image": b"img", "response_id": f"r{len(seen)}"}

    results = paint.paint_chain(
        call, b"photo", [scene(1850), scene(1950)], "De Adriaan", "Haarlem")
    assert [r["response_id"] for r in results] == ["r2", "r3"]
    assert seen == [(None, b"photo"), ("r1", None), ("r2", None)]  # photo only on anchor
    assert results[0]["year"] == 1850


def test_paint_parallel_branches_every_era_from_anchor():
    seen = []

    def call(prompt, prev_id, photo_bytes=None):
        seen.append(prev_id)
        if prev_id is None:
            return {"image": b"anchor", "response_id": "r-anchor"}
        return {"image": b"img", "response_id": "rx"}

    paint.paint_parallel(
        call, None, [scene(1850), scene(1950)], "De Adriaan", "Haarlem")
    assert seen[0] is None  # the anchor turn
    assert sorted(seen[1:]) == ["r-anchor", "r-anchor"]


def test_parallel_anchor_id_returned_first():
    ids = iter(["r-anchor", "r1", "r2"])

    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": next(ids)}

    results = paint.paint_parallel(
        call, None, [scene(1850)], "De Adriaan", "Haarlem")
    assert results[0]["response_id"] == "r1"


def test_paint_scene_keeps_matching_painting():
    def call(prompt, prev_id, photo_bytes=None):
        return {"image": b"img", "response_id": "r1"}

    out = paint.paint_scene(call, lambda image, p: "MATCHES whole mill.",
                            scene(1850), "De Adriaan", "Haarlem", "r0")
    assert out["image"] == b"img"
    assert out["verdict"] == "matches"
    assert out["attempts"] == 1


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
