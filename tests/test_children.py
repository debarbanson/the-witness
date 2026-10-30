"""Children's captions: rewritten for 8+, re-verified, or dropped."""

from witness import children


def test_child_caption_keeps_supported_rewrite():
    out = children.child_caption(
        rewrite_call=lambda adult, source, plain: "I was built in 1779.",
        support_call=lambda line, source: "supported",
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill")
    assert out == {"line": "I was built in 1779.", "verified": True,
                   "attempts": 1}


def test_child_caption_retries_plainer_once_then_drops():
    calls = []

    def rewrite(adult, source, plain):
        calls.append(plain)
        return "Too fancy." if not plain else "Still fancy."

    out = children.child_caption(
        rewrite_call=rewrite,
        support_call=lambda line, source: "unsupported",
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill")
    assert out == {"line": None, "verified": False, "attempts": 2}
    assert calls == [False, True]


def test_child_caption_plainer_retry_can_pass():
    def rewrite(adult, source, plain):
        return "Fancy." if not plain else "I was built in 1779."

    out = children.child_caption(
        rewrite_call=rewrite,
        support_call=lambda line, source: (
            "supported" if line == "I was built in 1779." else "unsupported"),
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill")
    assert out["line"] == "I was built in 1779."
    assert out["verified"] is True


def test_rewrite_prompt_constrains_to_source():
    prompt = children.rewrite_prompt("opened in 1779",
                                     "The mill was opened in 1779.")
    assert "8" in prompt
    assert "one idea" in prompt
    assert "The mill was opened in 1779." in prompt
    assert "opened in 1779" in prompt


def test_claim_for_line_matches_year_and_url_first():
    claims = [
        {"year": 1802, "url": "https://a.example/x", "quote": "First."},
        {"year": 1802, "url": "https://a.example/x", "quote": "Second."},
        {"year": 1802, "url": "https://b.example/y", "quote": "Other."},
    ]
    assert children.claim_for_line(
        claims, 1802, "https://a.example/x")["quote"] == "First."
    assert children.claim_for_line(claims, 1900, "https://a.example/x") is None


def test_child_caption_checks_a_bound_passage():
    seen = {}

    def support(line, passages):
        seen["passages"] = passages
        return "supported"

    out = children.child_caption(
        rewrite_call=lambda adult, source, plain: "I was built long ago.",
        support_call=support,
        adult="opened in 1779",
        source="The mill was opened in 1779 after years of work.",
        url="https://a.example/mill")
    assert out["verified"] is True
    assert seen["passages"] == [
        "https://a.example/mill\nThe mill was opened in 1779 after years of work."]
