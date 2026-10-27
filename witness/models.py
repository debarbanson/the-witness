"""Model settings: provider, base URL, model id and key name in one place.

Verification (step 3) and the visual check (step 5) run behind these
settings. Default is the Meta Model API; if the Baseten credits come,
point VERIFY and CHECK at meta-models/muse-spark-open-1026 on
https://inference.baseten.co/v1 with key BASETEN_API_KEY and nothing else
changes.
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
    return client.responses.create(model=spec.model, **kwargs)
