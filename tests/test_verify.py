"""Step 3: check each claim against its source snippets. No live calls."""

import json
from pathlib import Path

import pytest

from witness import verify

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_supported_claim():
    result = verify.verify_claim(
        lambda prompt: fixture("verify_supported.json"),
        "Built in 1932.",
        ["The tower was built in 1932 to a design by Hendrik Sangster."],
    )
    assert result["verdict"] == "supported"
    assert "1932" in result["quote"]
    assert result["rewritten"] is None


def test_partly_claim_is_rewritten():
    result = verify.verify_claim(
        lambda prompt: fixture("verify_partly.json"), "claim", ["snippet"]
    )
    assert result["verdict"] == "partly"
    assert result["rewritten"].startswith("The tower was decorated")


def test_unsupported_claim():
    result = verify.verify_claim(
        lambda prompt: fixture("verify_unsupported.json"), "claim", ["snippet"]
    )
    assert result["verdict"] == "unsupported"


def test_prompt_carries_claim_and_snippets():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return fixture("verify_supported.json")

    verify.verify_claim(respond, "Built in 1932.", ["snippet one", "snippet two"])
    assert "Built in 1932." in seen["prompt"]
    assert "snippet one" in seen["prompt"] and "snippet two" in seen["prompt"]
    assert "supported" in seen["prompt"] and "unsupported" in seen["prompt"]


def test_bad_verdicts_rejected():
    bad = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"verdict": "maybe"}', "annotations": []}]}]}
    with pytest.raises(verify.VerifyError):
        verify.verify_claim(lambda prompt: bad, "claim", ["snippet"])
    broken = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "not json", "annotations": []}]}]}
    with pytest.raises(verify.VerifyError):
        verify.verify_claim(lambda prompt: broken, "claim", ["snippet"])


def test_flag_content_war_and_politics():
    assert verify.flag_content("The mill was bombed during the war") == {"war"}
    assert verify.flag_content("In de oorlog werd de molen beschadigd") == {"war"}
    assert verify.flag_content("The council election of 1930") == {"politics"}
    assert verify.flag_content("Decorated with tulips in 1986") == set()


def test_fetch_wikipedia_full_article_in_own_language():
    get = FakeGet([(200, fixture("wiki_extract_full.json"))])
    text = verify.fetch_source_text("https://nl.wikipedia.org/wiki/Testtoren", get=get)
    assert "Tweede alinea" in text  # beyond the lead
    assert get.calls[0]["url"] == "https://nl.wikipedia.org/w/api.php"
    assert "extracts" in get.calls[0]["params"]["prop"]


def test_fetch_plain_page_extracts_main_text():
    html = (
        "<html><head><script>junk();</script></head><body><nav>menu</nav>"
        "<p>First real paragraph about the tower built in 1932.</p>"
        "<p>Short.</p>"
        "<p>Second real paragraph with enough words to keep for evidence.</p>"
        "</body></html>"
    )
    get = FakeGet([(200, html)])
    text = verify.fetch_source_text("https://example.com/page", get=get)
    assert "First real paragraph" in text
    assert "Second real paragraph" in text
    assert "junk" not in text and "Short." not in text
    assert get.calls[0]["headers"]["User-Agent"] == verify.USER_AGENT


def test_fetch_source_text_cached():
    get = FakeGet([(200, fixture("wiki_extract_full.json"))])
    url = "https://nl.wikipedia.org/wiki/Testtoren"
    verify.fetch_source_text(url, get=get)
    verify.fetch_source_text(url, get=get)
    assert len(get.calls) == 1


def test_fetch_source_text_uses_disk_cache(tmp_path):
    from witness.cache import Cache

    get = FakeGet([(200, fixture("wiki_extract_full.json"))])
    url = "https://nl.wikipedia.org/wiki/Testtoren"
    verify.fetch_source_text(url, get=get, cache=Cache(tmp_path))
    verify.clear_cache()
    text = verify.fetch_source_text(url, get=get, cache=Cache(tmp_path))
    assert len(get.calls) == 1
    assert "Tweede alinea" in text


def test_select_paragraphs_prefers_year_then_keywords():
    text = (
        "An unrelated opening line with enough words to count.\n\n"
        "In 1990 a heavy storm blew the tulips away.\n\n"
        "The tulips came back later after repairs were done.\n\n"
        "Another unrelated line with enough words to count here."
    )
    paras = verify.select_paragraphs(text, year=1990, keywords=["tulip"])
    assert "1990" in paras[0]
    assert any("came back" in p for p in paras)
    assert all("unrelated" not in p for p in paras)


def test_select_paragraphs_caps_and_falls_back():
    text = "Short intro.\n\n" + "\n\n".join(f"Paragraph {i} with enough words to count as one." for i in range(10))
    paras = verify.select_paragraphs(text, year=1800, keywords=["zzz"], max_paras=3)
    assert len(paras) == 3  # falls back to the head when nothing matches


def test_keywords_for_claim():
    words = verify.keywords_for_claim("repurposed: Remained in function until 1987", "repurposed")
    assert "repurposed" in words and "function" in words
    assert "in" not in words and "1987" not in words


class FakeGet:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        status, payload = self.script.pop(0)
        assert status == 200
        return FakeResponse(payload)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = payload if isinstance(payload, str) else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def clean_cache():
    verify.clear_cache()
    yield
    verify.clear_cache()


def test_verdict_records_supporting_url():
    answered = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"verdict": "supported", "quote": "q", "url": "https://example.com/p"}', "annotations": []}]}]}
    result = verify.verify_claim(lambda prompt: answered, "claim", ["snippet"])
    assert result["url"] == "https://example.com/p"
    missing = verify.verify_claim(
        lambda prompt: fixture("verify_supported.json"), "claim", ["snippet"]
    )
    assert missing["url"] is None


def test_support_prompt_is_passage_only():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return fixture("verify_supported.json")

    verify.verify_claim(respond, "claim", ["snippet"])
    assert "search" not in seen["prompt"].lower()
    assert '"completed"' not in seen["prompt"]


def test_search_fallback_prompt_invites_search():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return answered_with({"verdict": "supported", "quote": "q",
                              "url": "https://nl.wikipedia.org/wiki/X",
                              "support": [{"url": "https://nl.wikipedia.org/wiki/X",
                                           "supports": True, "quote": "q"}]})

    result = verify.verify_with_search(respond, "claim", ["https://example.com/x"])
    assert "search" in seen["prompt"].lower()
    assert result["verdict"] == "supported"


def answered_with(obj):
    import json as _json

    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": _json.dumps(obj), "annotations": []}],
            }
        ]
    }


def test_support_recorded_per_source_with_quotes():
    result = verify.verify_claim(
        lambda prompt: answered_with(
            {
                "verdict": "supported",
                "quote": "Built in 1932.",
                "url": "https://nl.wikipedia.org/wiki/X",
                "support": [
                    {"url": "https://nl.wikipedia.org/wiki/X", "supports": True, "quote": "Built in 1932."},
                    {"url": "https://example.com/y", "supports": False, "quote": ""},
                ],
            }
        ),
        "claim",
        ["snippet"],
    )
    assert result["verdict"] == "supported"
    assert result["support"][0] == {
        "url": "https://nl.wikipedia.org/wiki/X",
        "supports": True,
        "quote": "Built in 1932.",
    }


def test_weak_only_support_drops_the_claim():
    result = verify.verify_claim(
        lambda prompt: answered_with(
            {
                "verdict": "supported",
                "quote": "Storm in 1990.",
                "url": "https://www.tripadvisor.co.nz/abc",
                "support": [
                    {"url": "https://www.tripadvisor.co.nz/abc", "supports": True, "quote": "Storm in 1990."},
                    {"url": "https://nl.wikipedia.org/wiki/X", "supports": False, "quote": ""},
                ],
            }
        ),
        "claim",
        ["snippet"],
    )
    assert result["verdict"] == "unsupported"
    assert result["note"] == "weak sources only"


def test_good_source_quote_preferred():
    result = verify.verify_claim(
        lambda prompt: answered_with(
            {
                "verdict": "supported",
                "quote": "weak words",
                "url": "https://www.tripadvisor.co.nz/abc",
                "support": [
                    {"url": "https://www.tripadvisor.co.nz/abc", "supports": True, "quote": "weak words"},
                    {"url": "https://nl.wikipedia.org/wiki/X", "supports": True, "quote": "good words"},
                ],
            }
        ),
        "claim",
        ["snippet"],
    )
    assert result["verdict"] == "supported"
    assert result["quote"] == "good words"
    assert result["url"] == "https://nl.wikipedia.org/wiki/X"


def test_no_supporting_source_is_unsupported():
    result = verify.verify_claim(
        lambda prompt: answered_with(
            {
                "verdict": "supported",
                "quote": "",
                "support": [{"url": "https://nl.wikipedia.org/wiki/X", "supports": False, "quote": ""}],
            }
        ),
        "claim",
        ["snippet"],
    )
    assert result["verdict"] == "unsupported"


def test_completion_check_is_strict_about_plans():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return answered_with({"completed": True})

    assert verify.check_completion(respond, "claim", "quote")["completed"] is True
    assert "planned" in seen["prompt"] and "attempted" in seen["prompt"]
    failed = verify.check_completion(
        lambda prompt: answered_with({"completed": False}), "claim", "quote")
    assert failed["completed"] is False
    with pytest.raises(verify.VerifyError):
        verify.check_completion(
            lambda prompt: answered_with({"completed": "maybe"}), "claim", "quote")


def test_verify_all_runs_jobs_and_keeps_order():
    results = verify.verify_all(
        lambda prompt: fixture("verify_supported.json"),
        [("claim one", ["s1"]), ("claim two", ["s2"]), ("claim three", ["s3"])],
        max_workers=2,
    )
    assert [r["verdict"] for r in results] == ["supported"] * 3


def test_verify_all_captures_job_errors():
    def respond(prompt):
        if "bad" in prompt:
            raise verify.VerifyError("no messages")
        return fixture("verify_supported.json")

    results = verify.verify_all(respond, [("good", ["s"]), ("bad", ["s"])], max_workers=2)
    assert results[0]["verdict"] == "supported"
    assert results[1]["verdict"] == "unsupported"
    assert "no messages" in results[1]["note"]


def test_war_politics_only_flag_defaults_and_parses():
    result = verify.verify_claim(
        lambda prompt: fixture("verify_supported.json"), "claim", ["snippet"]
    )
    assert result["war_politics_only"] is False
    flagged = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"verdict": "supported", "quote": "q", "war_politics_only": true}', "annotations": []}]}]}
    result = verify.verify_claim(lambda prompt: flagged, "claim", ["snippet"])
    assert result["war_politics_only"] is True


def test_precheck_needs_year_and_keyword_in_one_passage():
    passage = "De watertoren is sinds 1986 opgesierd met een metershoge tulp."
    assert verify.precheck_hit(1986, ["tulip", "meters", "decorated"], [passage]) is True
    assert verify.precheck_hit(1986, ["tulip", "meters"], ["unrelated line here"]) is False
    assert verify.precheck_hit(1990, ["tulip", "meters"], [passage]) is False
    assert verify.precheck_hit(None, ["tulip"], [passage]) is False


def test_quote_prefers_best_source_rank():
    result = verify.verify_claim(
        lambda prompt: answered_with(
            {
                "verdict": "supported",
                "quote": "aggregator words",
                "url": "https://secretgb.co.uk/major-oak",
                "support": [
                    {"url": "https://secretgb.co.uk/major-oak", "supports": True,
                     "quote": "aggregator words"},
                    {"url": "https://en.wikipedia.org/wiki/Major_Oak", "supports": True,
                     "quote": "encyclopedia words"},
                ],
            }
        ),
        "claim",
        ["snippet"],
    )
    assert result["quote"] == "encyclopedia words"
    assert result["url"] == "https://en.wikipedia.org/wiki/Major_Oak"


def scripted_support(*verdicts):
    calls = []

    def respond(prompt):
        calls.append(prompt)
        verdict = verdicts[min(len(calls) - 1, len(verdicts) - 1)]
        return answered_with(
            {"verdict": verdict, "quote": f"{verdict} quote",
             "url": "https://en.wikipedia.org/wiki/X",
             "support": [{"url": "https://en.wikipedia.org/wiki/X",
                          "supports": verdict != "unsupported",
                          "quote": f"{verdict} quote"}]}
        )

    respond.calls = calls
    return respond


def job(**overrides):
    base = {"claim": "Built in 1932.", "event": "built", "detail": "Built in 1932.",
            "year": 1932, "keywords": ["built"], "passages": ["Built in 1932 here."],
            "urls": ["https://en.wikipedia.org/wiki/X"], "votes": 1}
    base.update(overrides)
    return base


def test_judge_single_vote_supported():
    result = verify.judge_claim(scripted_support("supported"), job())
    assert result["verdict"] == "supported"
    assert result["completed"] is True
    assert len(result["rounds"]) == 1


def test_judge_majority_of_three_wins():
    respond = scripted_support("supported", "unsupported", "supported")
    result = verify.judge_claim(
        respond, job(votes=3),
        completion_respond=lambda prompt: answered_with({"completed": True}))
    assert result["verdict"] == "supported"
    assert len(respond.calls) == 3
    assert len(result["rounds"]) == 3


def test_judge_tie_goes_to_last_round():
    respond = scripted_support("unsupported", "supported", "partly")
    result = verify.judge_claim(
        respond, job(votes=3, keywords=["zzz"], passages=["Built here."]))
    assert result["verdict"] == "partly"
    assert len(result["rounds"]) == 3


def test_judge_unsupported_with_evidence_gets_second_judgement():
    passages = ["De watertoren is sinds 1986 opgesierd met een metershoge tulp."]
    respond = scripted_support("unsupported", "supported")
    result = verify.judge_claim(
        respond, job(year=1986, keywords=["meters", "tulip"], passages=passages),
        completion_respond=lambda prompt: answered_with({"completed": True}))
    assert result["verdict"] == "supported"
    assert len(respond.calls) == 2
    assert "1986" in respond.calls[1]


def test_judge_unsupported_without_evidence_stands():
    respond = scripted_support("unsupported", "supported")
    result = verify.judge_claim(respond, job(keywords=["zzz"], passages=["Built here."]))
    assert result["verdict"] == "unsupported"
    assert len(respond.calls) == 1


def test_judge_search_fallback_without_passages():
    search = scripted_support("supported")
    support = scripted_support("supported")
    result = verify.judge_claim(support, job(passages=[]), search_respond=search,
                                completion_respond=search)
    assert result["verdict"] == "supported"
    assert len(support.calls) == 0
    assert len(search.calls) == 2  # one vote plus the completion check


def test_judge_completion_only_for_state_setting_claims():
    asked = []

    def completion(prompt):
        asked.append(prompt)
        return answered_with({"completed": True})

    verify.judge_claim(scripted_support("supported"),
                       job(event="burnt", detail="Burnt down."),
                       completion_respond=completion)
    assert len(asked) == 1
    verify.judge_claim(scripted_support("supported"),
                       job(event="renamed", detail="Renamed after a major."),
                       completion_respond=completion)
    assert len(asked) == 1


def test_judge_skips_completion_when_asked():
    asked = []

    def completion(prompt):
        asked.append(prompt)
        return answered_with({"completed": False})

    result = verify.judge_claim(scripted_support("supported"),
                                job(event="burnt", detail="Burnt down."),
                                completion_respond=completion, completion=False)
    assert result["completed"] is True
    assert asked == []


def test_judge_completion_failure_keeps_claim_with_note():
    def completion(prompt):
        raise verify.VerifyError("bad json")

    result = verify.judge_claim(scripted_support("supported"),
                                job(event="burnt", detail="Burnt down."),
                                completion_respond=completion)
    assert result["verdict"] == "supported"
    assert result["completed"] is True
    assert result["completion_note"] is not None


def test_judge_all_runs_jobs_and_keeps_order():
    results = verify.judge_all(
        lambda prompt: fixture("verify_supported.json"),
        [job(), job()], max_workers=2,
    )
    assert [r["verdict"] for r in results] == ["supported"] * 2


def test_judge_all_captures_job_errors():
    def respond(prompt):
        if "bad" in prompt:
            raise verify.VerifyError("no messages")
        return fixture("verify_supported.json")

    results = verify.judge_all(respond, [job(), job(claim="bad claim")], max_workers=2)
    assert results[0]["verdict"] == "supported"
    assert results[1]["verdict"] == "unsupported"


def test_regression_tower_1986_supported_1990_weak_only():
    tulips = verify.judge_claim(
        lambda prompt: answered_with(
            {"verdict": "supported",
             "quote": "De watertoren is sinds 1986 opgesierd met een metershoge tulp.",
             "url": "https://nl.wikipedia.org/wiki/Watertoren_(Roelofarendsveen)",
             "support": [
                 {"url": "https://nl.wikipedia.org/wiki/Watertoren_(Roelofarendsveen)",
                  "supports": True,
                  "quote": "De watertoren is sinds 1986 opgesierd met een metershoge tulp."}]}),
        job(claim="decorated: tower decorated with tulips since 1986.", event="decorated",
            detail="Decorated with tulips.", year=1986, keywords=["tulip", "meters"],
            passages=["De watertoren is sinds 1986 opgesierd met een metershoge tulp."]),
    )
    assert tulips["verdict"] == "supported"
    storm = verify.judge_claim(
        lambda prompt: answered_with(
            {"verdict": "supported",
             "quote": "The tulips were blown off by a heavy storm.",
             "url": "https://www.tripadvisor.in/x",
             "support": [
                 {"url": "https://www.tripadvisor.in/x", "supports": True,
                  "quote": "The tulips were blown off by a heavy storm."},
                 {"url": "https://nl.wikipedia.org/wiki/Watertoren_(Roelofarendsveen)",
                  "supports": False, "quote": ""}]}),
        job(claim="damaged: tulips blown off in 1990.", event="damaged",
            year=1990, keywords=["storm"]),
    )
    assert storm["verdict"] == "unsupported"
    assert storm["note"] == "weak sources only"


def test_regression_de_adriaan_states_and_1963_not_completed():
    assert verify.judge_claim(
        scripted_support("supported"), job(year=1779))["verdict"] == "supported"
    assert verify.judge_claim(
        scripted_support("supported"),
        job(event="burnt", detail="Completely burnt down.", year=1932))["verdict"] == "supported"
    opened = verify.judge_claim(
        scripted_support("supported"),
        job(event="rebuilt", detail="Reopened in 2002.", year=2002))
    assert opened["verdict"] == "supported"
    promise = verify.judge_claim(
        scripted_support("supported"),
        job(event="restored", year=1963,
            detail="Took an obligation to rebuild; the promise fell into oblivion."),
        completion_respond=lambda prompt: answered_with({"completed": False}),
    )
    assert promise["completed"] is False


def test_text_answer_wraps_plain_text_as_response():
    shaped = verify.text_answer('{"verdict": "supported"}')
    assert shaped["output"][0]["content"][0]["text"] == '{"verdict": "supported"}'
    result = verify.verify_claim(lambda prompt: shaped, "claim", ["snippet"])
    assert result["verdict"] == "supported"  # legacy answers without per-source support


def test_regression_eiffel_1967_proposal_is_caption_only():
    from witness import states

    assert states.classify("moved-proposed", "Secret agreement to dismantle and relocate.") is None
