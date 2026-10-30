"""Subject policy: war-dominated, political, hateful and
private-person content, in English and Dutch, never reaches the film.

A factual mention of war inside an object claim still films; a claim
that is only about war, politics, hate or a private person never
becomes a scene, line, caption or source. A subject whose accepted
claims are all refused is too little, with the reason saying so.
"""

from witness import captions
from witness import outcome
from witness import scenes
from witness import verify
from witness.render import builder


def claim(year, text, verdict="supported", war=False, refused=False,
          url="https://example.com/x"):
    return {"year": year, "claim": text, "quote_span": text,
            "event": "stood", "detail": text, "verdict": verdict,
            "war_politics_only": war, "refused_content": refused,
            "url": url, "quote": f"Source words: {text}",
            "sources": [url], "completed": True, "visible_change": "",
            "date_text": f"in {year}"}


EN = [
    ("war", "The regiment shelled the mill in 1944.", True, False),
    ("politics", "The council nationalised the mill in 1948.", True, False),
    ("hate", "Slur-laden graffiti about the miller appeared in 1950.", False, True),
    ("private", "The miller's daughter married in the mill in 1952.", False, True),
    ("mention", "The mill survived the war undamaged.", False, False),
    ("object", "The mill was restored in 1960.", False, False),
]

NL = [
    ("war", "Het regiment beschoot de molen in 1944.", True, False),
    ("politics", "De gemeente nationaliseerde de molen in 1948.", True, False),
    ("hate", "Er verscheen een haatleus over de molenaar in 1950.", False, True),
    ("private", "De dochter van de molenaar trouwde in de molen in 1952.", False, True),
    ("mention", "De molen overleefde de oorlog onbeschadigd.", False, False),
    ("object", "De molen werd gerestaureerd in 1960.", False, False),
]


def case_claims(cases, start=1944):
    return [claim(start + i * 2, text, war=war, refused=refused)
            for i, (_, text, war, refused) in enumerate(cases)]


def test_refused_marks_war_and_refused_content():
    for cases in (EN, NL):
        for kind, text, war, refused in cases:
            made = claim(1950, text, war=war, refused=refused)
            assert verify.refused(made) is (war or refused), kind
            assert verify.filmed(made) is not (war or refused), kind


def test_factual_mention_films_but_theme_does_not():
    for cases in (EN, NL):
        mention = next(c for c in cases if c[0] == "mention")
        made = claim(1944, mention[1])
        assert verify.filmed(made) is True
        themed = case_claims([c for c in cases if c[0] in ("war", "politics", "hate")])
        result = outcome.decide(themed, identified=True)
        assert result["outcome"] == "too_little"
        assert "refused" in result["reason"] or "war" in result["reason"]


def test_mixed_subject_films_without_refused_claims():
    for cases in (EN, NL):
        kept = case_claims(cases)
        usable = [c for c in kept if verify.filmed(c)]
        assert {c["claim"] for c in usable} == {
            next(c[1] for c in cases if c[0] == "mention"),
            next(c[1] for c in cases if c[0] == "object"),
        }
        result = outcome.decide(kept, identified=True)
        assert result["verified"] == 2


def test_refused_claims_never_become_scenes_or_lines():
    for cases in (EN, NL):
        kept = case_claims(cases)
        timeline = [{"from_year": 1930, "to_year": None,
                     "state": {"condition": "standing", "degree": "total",
                               "scope": "whole", "description": ""}}]
        chosen = scenes.choose_scenes(timeline, kept)
        years = {s["from_year"] for s in chosen
                 if isinstance(s["from_year"], int)}
        refused_years = {c["year"] for c in kept if verify.refused(c)}
        assert not (years & refused_years)
        lines = [line for s in chosen for line in s["caption_lines"]]
        assert not (refused_years & {line["year"] for line in lines})


def test_refused_claims_match_no_caption():
    for cases in (EN, NL):
        kept = case_claims(cases)
        for made in kept:
            assert captions.claim_matches(made, made["year"]) is verify.filmed(made)


def test_refused_claims_never_become_sources():
    for cases in (EN, NL):
        kept = case_claims(cases)
        for made in kept:
            if verify.refused(made):
                made["url"] = "https://refused.example/x"
            else:
                made["url"] = "https://kept.example/x"
            made["quote"] = f"{made['url']} quote here for provenance."
        filmed_scenes = [{
            "from_year": made["year"], "date_label": str(made["year"]),
            "state": {"condition": "standing"}, "caption_lines": [],
            "caption_sentence": {
                "text": f"Words for {made['year']}.",
                "claim_year": made["year"], "claim_url": made["url"],
                "evidence": {"claim": made["claim"], "url": made["url"],
                             "quote": made["quote"]}}}
            for made in kept]
        urls = [entry["url"]
                for entry in builder.end_sources(filmed_scenes, kept, None)]
        assert urls == ["https://kept.example/x"]


def test_flag_content_marks_the_theme_in_four_languages():
    assert verify.flag_content("The regiment shelled the mill.") == {"war"}
    assert verify.flag_content("The council nationalised the mill.") == {"politics"}
    assert verify.flag_content("The mill's political history is long.") == {"politics"}
    assert verify.flag_content("Het regiment beschoot de molen.") == {"war"}
    assert verify.flag_content("De gemeente nationaliseerde de molen.") == {"politics"}
    assert verify.flag_content("Das Regiment beschoss die Mühle im Krieg.") == {"war"}
    assert verify.flag_content("Die Wahl des Bürgermeisters war knapp.") == {"politics"}
    assert verify.flag_content("Le régiment a bombardé le moulin pendant la guerre.") == {"war"}
    assert verify.flag_content("L'élection du maire a fait débat.") == {"politics"}
    assert verify.flag_content("The mill was restored in 1960.") == set()


def test_flag_content_treats_survival_as_a_mention_not_a_theme():
    assert verify.flag_content("The mill survived the war undamaged.") == set()
    assert verify.flag_content("De molen overleefde de oorlog onbeschadigd.") == set()
    assert verify.flag_content("Die Mühle überstand den Krieg unbeschadet.") == set()
    assert verify.flag_content("Le moulin a survécu à la guerre intact.") == set()
    assert verify.flag_content("The mill was bombed in the war.") == {"war"}


def test_object_gate_refuses_war_and_politics_subjects():
    assert verify.object_refused("War Memorial", "memorial", "") == {"war"}
    assert verify.object_refused("Oorlogsmonument", "monument", "") == {"war"}
    assert verify.object_refused("Hungarian Parliament Building", "parliament", "") == {"politics"}
    assert verify.object_refused("Reichstag", "parliament building", "") == {"politics"}
    assert verify.object_refused("De Adriaan", "windmill", "") == set()
