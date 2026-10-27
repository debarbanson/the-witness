"""Step 6: one RGBA layer per figure, for parallax. No live calls."""

from pathlib import Path

from PIL import Image

from witness import layers

FIXTURES = Path(__file__).parent / "fixtures"


def fake_photo(path, size=(200, 160)):
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def test_figures_returns_one_layer_per_person_largest_first(tmp_path):
    raw = (FIXTURES / "sam_persons.txt").read_text()
    found = layers.figures(lambda text, jpg: raw,
                           fake_photo(tmp_path / "era.png"))
    assert len(found) == 2
    assert found[0]["image"].mode == "RGBA"
    assert found[0]["image"].size == (200, 160)
    area = [layer["box"][2] * layer["box"][3] for layer in found]
    assert area[0] >= area[1]
    assert found[0]["box"] != found[1]["box"]


def test_figures_caps_at_sixteen(tmp_path):
    raw = (FIXTURES / "sam_persons.txt").read_text()
    found = layers.figures(lambda text, jpg: raw,
                           fake_photo(tmp_path / "era.png"), max_figures=1)
    assert len(found) == 1


def test_figures_empty_when_nobody_found(tmp_path):
    found = layers.figures(lambda text, jpg: "no objects here\n",
                           fake_photo(tmp_path / "era.png"))
    assert found == []
