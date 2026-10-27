"""Step 3b: enough for a film? Pure logic, fully unit-tested."""

from witness import outcome


def claim(year, event="stood", verdict="supported", sources=("https://nl.wikipedia.org/wiki/X",), war=False):
    return {
        "year": year,
        "event": event,
        "verdict": verdict,
        "rewritten": "rewritten text" if verdict == "partly" else None,
        "sources": list(sources),
        "war_politics_only": war,
    }


WIKI = "https://nl.wikipedia.org/wiki/X"
ARCHIVE = "https://archief.example.nl/doc/1"


def full_set():
    return [
        claim(1932, "built", sources=[WIKI]),
        claim(1986, "restored", sources=[WIKI]),
        claim(1987, "repurposed", sources=[ARCHIVE]),
        claim(1990, "damaged", sources=[WIKI]),
        claim(1991, "restored", sources=[ARCHIVE]),
    ]


def test_full_film_on_all_thresholds():
    result = outcome.decide(full_set(), identified=True)
    assert result["outcome"] == "full_film"
    assert (result["verified"], result["eras"], result["good_sources"]) == (5, 5, 2)
    assert result["build_year"] is True


def test_full_film_exact_boundaries():
    claims = [
        claim(1932, "built", sources=[WIKI]),
        claim(1940, sources=[WIKI]),
        claim(1950, sources=[WIKI]),
        claim(1960, sources=[WIKI]),
        claim(1970, sources=[ARCHIVE]),
    ]
    assert outcome.decide(claims, identified=True)["outcome"] == "full_film"


def test_missing_build_year_drops_to_short():
    claims = [dict(c, event="stood") for c in full_set()]
    result = outcome.decide(claims, identified=True)
    assert result["outcome"] == "short_film"
    assert result["build_year"] is False


def test_single_source_drops_to_short():
    claims = [dict(c, sources=[WIKI]) for c in full_set()]
    assert outcome.decide(claims, identified=True)["outcome"] == "short_film"


def test_four_claims_is_short():
    assert outcome.decide(full_set()[:4], identified=True)["outcome"] == "short_film"


def test_three_claims_two_eras_is_short():
    claims = [claim(1932, "built"), claim(1932, "stood"), claim(1991, "stood")]
    assert outcome.decide(claims, identified=True)["outcome"] == "short_film"


def test_three_claims_one_era_is_too_little():
    claims = [claim(1932, "built"), claim(1932, "stood"), claim(1932, "stood")]
    assert outcome.decide(claims, identified=True)["outcome"] == "too_little"


def test_two_claims_is_too_little():
    assert outcome.decide(full_set()[:2], identified=True)["outcome"] == "too_little"


def test_partly_counts_only_with_rewrite():
    claims = [
        claim(1932, "built"),
        claim(1940, verdict="partly"),
        claim(1950, verdict="partly"),
        claim(1960, verdict="unsupported"),
    ]
    result = outcome.decide(claims, identified=True)
    assert result["verified"] == 3  # supported + 2 rewritten partlies
    assert result["outcome"] == "short_film"
    bare = dict(claims[1], rewritten=None)
    result = outcome.decide([claims[0], bare], identified=True)
    assert result["verified"] == 1
    assert result["outcome"] == "too_little"


def test_war_only_claims_do_not_count():
    claims = full_set() + [claim(1945, verdict="supported", war=True)]
    result = outcome.decide(claims, identified=True)
    assert result["verified"] == 5
    only_war = [claim(1942, war=True), claim(1943, war=True), claim(1944, war=True)]
    assert outcome.decide(only_war, identified=True)["outcome"] == "too_little"


def test_weak_only_sources_do_not_count_as_good():
    weak = "https://www.tripadvisor.co.nz/abc"
    claims = [dict(c, sources=[weak]) for c in full_set()]
    result = outcome.decide(claims, identified=True)
    assert result["good_sources"] == 0
    assert result["outcome"] == "short_film"


def test_not_identified_wins_over_claims():
    result = outcome.decide(full_set(), identified=False)
    assert result["outcome"] == "not_identified"


def test_empty_claims_is_too_little():
    assert outcome.decide([], identified=True)["outcome"] == "too_little"


def film_with(outcome_name, segments, scene_years):
    return {
        "outcome": {"outcome": outcome_name},
        "timeline": [
            {"from_year": year, "to_year": None,
             "state": {"condition": cond, "description": text}}
            for year, cond, text in segments
        ],
        "scenes": [{"from_year": y} for y in scene_years],
    }


def test_film_signature_ignores_wording():
    first = film_with("full_film",
                      [(1779, "standing", "mill erected"), (1932, "ruin", "burnt")],
                      [1779, 1932, "today"])
    second = film_with("full_film",
                       [(1779, "standing", "octagonal mill built"), (1932, "ruin", "destroyed")],
                      [1779, 1932, "today"])
    assert outcome.film_signature(first) == outcome.film_signature(second)


def test_film_signature_catches_condition_and_year_changes():
    base = film_with("full_film",
                     [(1779, "standing", "mill erected"), (1932, "ruin", "burnt")],
                     [1779, 1932, "today"])
    assert outcome.film_signature(film_with(
        "short_film", [(1779, "standing", "x")], [1779, "today"])) != outcome.film_signature(base)
    assert outcome.film_signature(film_with(
        "full_film", [(1779, "standing", "x"), (1932, "burnt", "y")],
        [1779, 1932, "today"])) != outcome.film_signature(base)
    assert outcome.film_signature(film_with(
        "full_film", [(1779, "standing", "x"), (1932, "ruin", "y")],
        [1779, 1930, "today"])) != outcome.film_signature(base)
