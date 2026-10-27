"""One setting per model-using step, so switching provider is configuration."""

import pytest

from witness import models


def test_verify_defaults_to_meta_model_api():
    assert models.VERIFY.provider == "meta"
    assert models.VERIFY.base_url == "https://api.meta.ai/v1"
    assert models.VERIFY.model == "muse-spark-1.3"
    assert models.VERIFY.key_name == "MODEL_API_KEY"


def test_check_shares_the_verify_setting_until_it_needs_its_own():
    assert models.CHECK == models.VERIFY


def test_client_uses_base_url_and_key_from_environment():
    client = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    assert str(client.base_url) == "https://api.meta.ai/v1/"
    assert client.api_key == "k-123"


def test_missing_key_names_the_variable_not_a_value():
    with pytest.raises(models.ModelError) as exc_info:
        models.client_for(models.VERIFY, environ={})
    assert "MODEL_API_KEY" in str(exc_info.value)
    assert "k-123" not in str(exc_info.value)


def test_verify_and_vision_run_low_effort_research_default():
    assert models.VERIFY.effort == "low"
    assert models.VISION.effort == "low"
    assert models.RESEARCH.effort is None


def test_verify_runs_temperature_zero():
    assert models.VERIFY.temperature == 0
    assert models.RESEARCH.temperature is None


def test_respond_injects_model_and_effort():
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return "ok"

    class FakeClient:
        responses = FakeResponses()

    assert models.respond(FakeClient(), models.VERIFY, input="hi") == "ok"
    assert calls[0]["model"] == "muse-spark-1.3"
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert calls[0]["temperature"] == 0
    calls.clear()
    models.respond(FakeClient(), models.RESEARCH, input="hi")
    assert "reasoning" not in calls[0]
    assert "temperature" not in calls[0]


def test_switching_to_baseten_is_configuration():
    baseten = models.ModelSpec(
        provider="baseten",
        base_url="https://inference.baseten.co/v1",
        model="meta-models/muse-spark-open-1026",
        key_name="BASETEN_API_KEY",
    )
    client = models.client_for(baseten, environ={"BASETEN_API_KEY": "b-456"})
    assert str(client.base_url) == "https://inference.baseten.co/v1/"
    assert client.api_key == "b-456"
    assert baseten.model == "meta-models/muse-spark-open-1026"


def test_verify_open_points_at_baseten_hackathon_model():
    assert models.VERIFY_OPEN.provider == "baseten"
    assert models.VERIFY_OPEN.base_url == "https://inference.baseten.co/v1"
    assert models.VERIFY_OPEN.model == "meta-models/muse-spark-open-1026"
    assert models.VERIFY_OPEN.key_name == "BASETEN_API_KEY"
    assert models.VERIFY_OPEN.temperature == 0


class FakeChatCompletions:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


class FakeChatClient:
    def __init__(self, answer):
        self.chat = type("chat", (), {"completions": FakeChatCompletions(answer)})()


def chat_answer(content, reasoning="", prompt=10, completion=5):
    message = {"content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": prompt + completion},
    }


def test_chat_injects_model_and_temperature():
    client = FakeChatClient(chat_answer("hi"))
    models.chat(client, models.VERIFY_OPEN, [{"role": "user", "content": "hi"}])
    call = client.chat.completions.calls[0]
    assert call["model"] == "meta-models/muse-spark-open-1026"
    assert call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_answer_separates_reasoning_and_counts_tokens():
    parsed = models.chat_answer(chat_answer("final", reasoning="thinking", prompt=10, completion=5))
    assert parsed["content"] == "final"
    assert parsed["reasoning"] == "thinking"
    assert parsed["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    bare = models.chat_answer({"choices": [{"message": {"content": "x"}}]})
    assert bare == {"content": "x", "reasoning": "", "usage": {}}


def test_usage_accumulates_per_provider():
    models.reset_usage()
    models.note_usage("meta", {"prompt_tokens": 10, "completion_tokens": 5})
    models.note_usage("baseten", {"prompt_tokens": 3, "completion_tokens": 1})
    models.note_usage("meta", {"prompt_tokens": 2, "completion_tokens": 1})
    assert models.usage_totals() == {
        "meta": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        "baseten": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }
    models.reset_usage()
    assert models.usage_totals() == {}


def test_paint_uses_muse_image_on_meta():
    assert models.PAINT.provider == "meta"
    assert models.PAINT.model == "muse-image-1.0"
    assert models.PAINT.key_name == "MODEL_API_KEY"
    assert models.PAINT.effort is None
    assert models.PAINT.temperature is None
