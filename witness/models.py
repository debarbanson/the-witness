"""Model settings: provider, base URL, model id and key name in one place.

Research, vision and the search fallback run on the Meta Model API
(Responses calls). Passage-only support checks can run on Meta (VERIFY)
or on the open-weights Muse Spark Open via Baseten (VERIFY_OPEN, Chat
Completions; credits granted 27 Oct). Token use is tallied per provider
for the cost report.
"""

import os
from dataclasses import dataclass


class ModelError(Exception):
    """A model is misconfigured (its key is missing)."""


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    base_url: str
    model: str
    key_name: str
    effort: str | None = None  # reasoning effort; None keeps the default
    temperature: float | None = None  # None keeps the default; 0 steadies checks
    workers: int = 6  # parallel calls; Baseten allows more (2M tokens/min)


RESEARCH = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
)

VISION = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
)

VERIFY = ModelSpec(
    provider="meta",
    base_url="https://api.meta.ai/v1",
    model="muse-spark-1.3",
    key_name="MODEL_API_KEY",
    effort="low",
    temperature=0,  # probed 27 Oct: accepted; seed is not in the SDK surface
)

# Step 5 shares the verify setting until it needs its own.
CHECK = VERIFY

# Open-weights support checks on Baseten (credits granted 27 Oct). The
# hackathon key only works with the -1026 model name, not the name in
# Baseten's own docs. Chat Completions path; Meta stays on Responses.
VERIFY_OPEN = ModelSpec(
    provider="baseten",
    base_url="https://inference.baseten.co/v1",
    model="meta-models/muse-spark-open-1026",
    key_name="BASETEN_API_KEY",
    temperature=0,
    # 2M tokens/min throughput: ~15k tokens per support call allows
    # about 130 calls/min, so 10 workers at ~3 s a call stays inside.
    workers=10,
)


def client_for(spec, environ=None):
    """OpenAI-compatible client for a spec. Key never leaves the environment."""
    from openai import OpenAI

    env = environ if environ is not None else os.environ
    key = env.get(spec.key_name)
    if not key:
        raise ModelError(f"{spec.key_name} is not set (needed for {spec.provider}/{spec.model})")
    return OpenAI(base_url=spec.base_url, api_key=key)


def respond(client, spec, **kwargs):
    """One Responses call: model id, reasoning effort and temperature injected."""
    if spec.effort is not None:
        kwargs["reasoning"] = {"effort": spec.effort}
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    response = client.responses.create(model=spec.model, **kwargs)
    note_usage(spec.provider, getattr(response, "usage", None))
    return response


def chat(client, spec, messages, **kwargs):
    """One Chat Completions call (the Baseten path): model id and
    temperature injected. No reasoning control: Muse Spark Open always
    reasons; read the answer with chat_answer."""
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    response = client.chat.completions.create(model=spec.model, messages=messages, **kwargs)
    note_usage(spec.provider, getattr(response, "usage", None))
    return response


def chat_answer(response) -> dict:
    """Final answer text, reasoning kept separate, token counts."""
    if isinstance(response, dict):
        message = response["choices"][0]["message"]
        content = message.get("content", "")
        reasoning = message.get("reasoning_content", "")
        usage = response.get("usage", {}) or {}
    else:
        message = response.choices[0].message
        content = message.content or ""
        reasoning = getattr(message, "reasoning_content", "") or ""
        usage = _usage_dict(getattr(response, "usage", None))
    return {"content": content, "reasoning": reasoning, "usage": usage}


_USAGE: dict = {}


def reset_usage() -> None:
    _USAGE.clear()


def note_usage(provider: str, usage) -> None:
    """Add one call's token counts to the per-provider running totals."""
    counts = _usage_dict(usage)
    if not counts:
        return
    totals = _USAGE.setdefault(provider, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    for key in totals:
        totals[key] += counts.get(key, 0)


def usage_totals() -> dict:
    return {provider: dict(totals) for provider, totals in _USAGE.items()}


def _usage_dict(usage) -> dict:
    if usage is None or isinstance(usage, str):
        return {}
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    else:
        prompt = getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0))
        completion = getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0))
    try:
        return {"prompt_tokens": int(prompt or 0), "completion_tokens": int(completion or 0),
                "total_tokens": int(prompt or 0) + int(completion or 0)}
    except (TypeError, ValueError):
        return {}
