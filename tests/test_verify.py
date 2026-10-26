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


def test_fetch_evidence_reads_wikipedia_extracts():
    get = FakeGet([(200, fixture("wiki_extract.json"))])
    evidence = verify.fetch_evidence(
        ["https://nl.wikipedia.org/wiki/Testtoren", "https://example.com/page"],
        get=get,
    )
    assert len(evidence) == 1
    assert "1932" in evidence[0] and "nl.wikipedia.org" in evidence[0]
    assert "extracts" in get.calls[0]["params"]["prop"]


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

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_war_politics_only_flag_defaults_and_parses():
    result = verify.verify_claim(
        lambda prompt: fixture("verify_supported.json"), "claim", ["snippet"]
    )
    assert result["war_politics_only"] is False
    flagged = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"verdict": "supported", "quote": "q", "war_politics_only": true}', "annotations": []}]}]}
    result = verify.verify_claim(lambda prompt: flagged, "claim", ["snippet"])
    assert result["war_politics_only"] is True
