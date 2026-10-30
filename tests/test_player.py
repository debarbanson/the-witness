"""The film page player: one painting per era, no figure layers."""

import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("witness/render/film.html")
CHECK = Path(__file__).parent / "player_check.cjs"


def test_player_has_no_figure_layers():
    template = TEMPLATE.read_text()
    assert "syncLayers" not in template
    assert "clearLayers" not in template
    assert "layerKey" not in template
    assert 'id="layers"' not in template
    assert "translateX" not in template


def test_player_plays_the_finished_film():
    template = TEMPLATE.read_text()
    assert "Checking " not in template
    assert "readyAt(" not in template
    assert "REPLAY" not in template
    assert "ready_at" not in template


def test_clock_shows_unless_opted_out():
    template = TEMPLATE.read_text()
    assert 'params.has("noclock")' in template


def test_caption_is_never_clamped_or_cut():
    template = TEMPLATE.read_text()
    assert "line-clamp" not in template
    assert "…" not in template


def test_stage_does_not_shrink_in_narrow_viewports():
    assert "flex-shrink: 0" in TEMPLATE.read_text()


def test_end_card_shows_site_and_title():
    assert 's.site + ": " + s.title' in TEMPLATE.read_text()


def test_page_preloads_and_decodes_before_playing():
    template = TEMPLATE.read_text()
    assert "collectImages" in template
    assert "preload(" in template
    assert ".decode(" in template
    assert "__READY" in template


def test_image_load_failure_uses_progress_line():
    template = TEMPLATE.read_text()
    assert "cannot load its pictures" in template


def test_empty_today_line_gets_no_default():
    assert 'FILM.today_line ?? "And here I stand today."' in TEMPLATE.read_text()


def test_player_behavior_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    proc = subprocess.run(
        [node, str(CHECK), str(TEMPLATE)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr + proc.stdout
