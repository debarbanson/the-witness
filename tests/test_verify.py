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


def test_verify_prompt_invites_search_when_evidence_is_short():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return fixture("verify_supported.json")

    verify.verify_claim(respond, "claim", ["snippet"])
    assert "search" in seen["prompt"].lower()


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


def test_completed_flag_parses_and_defaults_true():
    done = verify.verify_claim(
        lambda prompt: answered_with({"verdict": "supported", "quote": "q"}),
        "claim",
        ["snippet"],
    )
    assert done["completed"] is True
    planned = verify.verify_claim(
        lambda prompt: answered_with({"verdict": "supported", "quote": "q", "completed": False}),
        "claim",
        ["snippet"],
    )
    assert planned["completed"] is False


def test_verify_prompt_is_strict_about_plans():
    seen = {}

    def respond(prompt):
        seen["prompt"] = prompt
        return fixture("verify_supported.json")

    verify.verify_claim(respond, "claim", ["snippet"])
    assert "planned" in seen["prompt"] and "attempted" in seen["prompt"]


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
