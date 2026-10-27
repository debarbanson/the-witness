"""Probe: does the Responses API accept temperature and seed? One tiny call each."""
import json
import sys

sys.path.insert(0, ".")

from witness import models

PROMPT = 'Reply with exactly this JSON object and nothing else: {"verdict": "supported"}'


def probe(label, **kwargs):
    try:
        resp = models.respond(models.client_for(models.VERIFY), models.VERIFY,
                              input=PROMPT, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the error is the finding
        print(f"{label}: REJECTED {type(exc).__name__}: {str(exc)[:200]}")
        return
    try:
        text = resp.output[-1].content[0].text
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: ACCEPTED but unreadable output: {exc!r}")
        return
    print(f"{label}: ACCEPTED -> {text[:120]}")


if __name__ == "__main__":
    probe("temperature=0", temperature=0)
    probe("temperature=0+seed=42", temperature=0, seed=42)
