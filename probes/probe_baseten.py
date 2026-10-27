"""Probe: Baseten hackathon model name, reasoning separation, usage shape. One call."""
import sys

sys.path.insert(0, ".")

from witness import models

PROMPT = (
    'Claim to check:\nThe tower was built in 1932.\n\n'
    'Source passages:\n1. https://nl.wikipedia.org/wiki/X\nDe toren is gebouwd in 1932.\n\n'
    'Answer with a JSON object only: {"verdict": "supported" | "unsupported", '
    '"quote": the supporting sentence}.'
)

try:
    resp = models.chat(models.client_for(models.VERIFY_OPEN), models.VERIFY_OPEN,
                       messages=[{"role": "user", "content": PROMPT}])
except Exception as exc:  # noqa: BLE001 - the error is the finding
    print(f"CALL FAILED {type(exc).__name__}: {str(exc)[:300]}")
    raise SystemExit(1)

parsed = models.chat_answer(resp)
print("model name accepted")
print("content:", parsed["content"][:200])
print("reasoning present:", bool(parsed["reasoning"]),
      f"({len(parsed['reasoning'])} chars)")
print("usage:", parsed["usage"])
