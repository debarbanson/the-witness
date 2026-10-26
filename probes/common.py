"""Shared helpers for the day-1 probes. Not part of the pipeline."""

import base64
import io
import json
import os
from pathlib import Path

from openai import OpenAI
from PIL import Image

BASE_URL = "https://api.meta.ai/v1"
OUT = Path("out/probes")


def client() -> OpenAI:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise SystemExit("MODEL_API_KEY is not set")
    return OpenAI(base_url=BASE_URL, api_key=key)


def save_json(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    return path


def save_text(name: str, text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(text)
    return path


def response_json(resp) -> dict:
    return json.loads(resp.model_dump_json())


def output_text(resp) -> str:
    """Concatenate all output_text content blocks of a Responses API result."""
    chunks: list[str] = []
    for item in resp.output or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", None) == "output_text":
                chunks.append(block.text)
    return "\n".join(chunks)


def data_uri(path: Path, max_dim: int = 1600) -> tuple[str, tuple[int, int]]:
    """JPEG data URI of path, downscaled so the long side is at most max_dim.

    Returns the URI and the (width, height) of the image that was encoded.
    """
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}", img.size
