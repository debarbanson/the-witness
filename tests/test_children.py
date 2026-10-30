"""Children's captions: rewritten for 8+, re-verified, or dropped."""

from witness import children


def test_child_caption_keeps_supported_rewrite():
    out = children.child_caption(
        rewrite_call=lambda adult, source, plain, gentle=False: "I was built in 1779.",
        support_call=lambda line, source: "supported",
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill")
    assert out == {"line": "I was built in 1779.", "verified": True,
                   "attempts": 1}


def test_child_caption_retries_plainer_once_then_drops():
    calls = []

    def rewrite(adult, source, plain, gentle=False):
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
    def rewrite(adult, source, plain, gentle=False):
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


def test_child_caption_judges_against_rich_passages():
    seen = {}
    texts = {"https://a.example/mill":
             "The old mill stood by the river for many years.\n\n"
             "The mill was opened in 1779 after years of building work."}

    def support(line, passages):
        seen["passages"] = passages
        return "supported"

    out = children.child_caption(
        rewrite_call=lambda adult, source, plain, gentle=False: "I opened long ago.",
        support_call=support,
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill",
        texts=texts)
    assert out["verified"] is True
    assert seen["passages"][0] == ("https://a.example/mill\n"
                                   "The mill was opened in 1779.")
    assert any("years of building work" in p for p in seen["passages"])


def test_child_caption_judges_with_object_and_year_context():
    seen = {}

    def support(line, passages):
        seen["judged"] = line
        return "supported"

    out = children.child_caption(
        rewrite_call=lambda adult, source, plain, gentle=False: "I opened long ago.",
        support_call=support,
        adult="opened in 1779",
        source="The mill was opened in 1779.",
        url="https://a.example/mill", year=1779, object_name="De Adriaan")
    assert out["verified"] is True
    assert out["line"] == "I opened long ago."
    assert seen["judged"] == "In 1779, De Adriaan: I opened long ago."


def test_claim_for_line_matches_scene_order_not_research_order():
    claims = [
        {"year": 1932, "url": "https://a.example/x", "quote": "Zebra quote.",
         "claim": "zebra thing"},
        {"year": 1932, "url": "https://a.example/x", "quote": "Apple quote.",
         "claim": "apple thing"},
    ]
    assert children.claim_for_line(
        claims, 1932, "https://a.example/x")["quote"] == "Apple quote."


def test_child_caption_checks_a_bound_passage():
    seen = {}

    def support(line, passages):
        seen["passages"] = passages
        return "supported"

    out = children.child_caption(
        rewrite_call=lambda adult, source, plain, gentle=False: "I was built long ago.",
        support_call=support,
        adult="opened in 1779",
        source="The mill was opened in 1779 after years of work.",
        url="https://a.example/mill")
    assert out["verified"] is True
    assert seen["passages"] == [
        "https://a.example/mill\nThe mill was opened in 1779 after years of work."]


def test_gentle_rewrite_for_heavy_states():
    assert "gently" in children.rewrite_prompt("I burnt down.", "source", gentle=True)
    assert "gently" not in children.rewrite_prompt("I stood tall.", "source")
    assert children.GENTLE_CONDITIONS >= {"damaged", "burnt", "ruin", "demolished"}
    assert "standing" not in children.GENTLE_CONDITIONS
    assert "rebuilt" not in children.GENTLE_CONDITIONS


def test_child_caption_threads_gentle_to_the_rewrite():
    seen = {}

    def rewrite(adult, source, plain, gentle=False):
        seen["gentle"] = gentle
        return "I caught fire."

    children.child_caption(
        rewrite_call=rewrite,
        support_call=lambda line, passages: "supported",
        adult="I burnt down.", source="The mill burnt down in 1932.",
        url="https://a.example/mill", gentle=True)
    assert seen["gentle"] is True
