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
    calls.clear()
    models.respond(FakeClient(), models.RESEARCH, input="hi")
    assert "reasoning" not in calls[0]


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
