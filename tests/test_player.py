"""The film page player: layers stay flat on the painting, built once."""

import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("witness/render/film.html")
CHECK = Path(__file__).parent / "player_check.cjs"


def test_layers_share_the_painting_transform():
    template = TEMPLATE.read_text()
    assert "translateX" not in template
    assert "img.style.transform = imgA.style.transform" in template


def test_layer_images_are_built_once_per_scene():
    assert "layerKey" in TEMPLATE.read_text()


def test_caption_is_never_clamped_or_cut():
    template = TEMPLATE.read_text()
    assert "line-clamp" not in template
    assert "…" not in template


def test_stage_does_not_shrink_in_narrow_viewports():
    assert "flex-shrink: 0" in TEMPLATE.read_text()


def test_end_card_shows_site_and_title():
    assert 's.site + ": " + s.title' in TEMPLATE.read_text()


def test_player_behavior_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    proc = subprocess.run(
        [node, str(CHECK), str(TEMPLATE)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr + proc.stdout
