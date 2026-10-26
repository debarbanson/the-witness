"""CLI helpers: slugs for any script and any accents."""

from witness.cli import slug_for


def test_slug_transliterates_accents():
    assert slug_for("Biosphère", "Q123", {}) == "q123-biosphere"


def test_slug_falls_back_to_english_article():
    assert slug_for("錦帯橋", "Q1196460", {"en": "Kintai Bridge"}) == "q1196460-kintai-bridge"


def test_slug_falls_back_to_wikidata_id():
    assert slug_for("錦帯橋", "Q1196460", {}) == "q1196460"


def test_slug_without_qid():
    assert slug_for("De Adriaan", None, {}) == "de-adriaan"
    assert slug_for("???", None, {}) == "film"
