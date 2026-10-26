"""Probe 3 (TEST): web_search plus structured output in one call.

Tries the Responses API spelling first (text.format with a JSON schema),
then the extra_body response_format spelling if the first is rejected.
Saves search_structured.json with what worked and what failed.
"""

import json

from probes.common import client, output_text, response_json, save_json

QUESTION = "When was the De Adriaan windmill in Haarlem built, and why?"

SCHEMA = {
    "type": "object",
    "properties": {
        "built_year": {"type": "string"},
        "reason": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["built_year", "reason", "sources"],
    "additionalProperties": False,
}


def main() -> None:
    report: dict = {"question": QUESTION, "attempts": []}
    resp = None

    try:
        resp = client().responses.create(
            model="muse-spark-1.3",
            tools=[{"type": "web_search"}],
            include=["web_search_call.results"],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "windmill_answer",
                    "schema": SCHEMA,
                    "strict": True,
                }
            },
            input=QUESTION,
        )
        report["attempts"].append({"spelling": "text.format", "status": "ok"})
    except Exception as exc:  # noqa: BLE001 - the failure is the finding
        report["attempts"].append(
            {"spelling": "text.format", "status": "error", "error": _short(exc)}
        )

    if resp is None:
        try:
            resp = client().responses.create(
                model="muse-spark-1.3",
                tools=[{"type": "web_search"}],
                include=["web_search_call.results"],
                input=QUESTION,
                extra_body={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "windmill_answer", "schema": SCHEMA},
                    }
                },
            )
            report["attempts"].append({"spelling": "extra_body.response_format", "status": "ok"})
        except Exception as exc:  # noqa: BLE001 - the failure is the finding
            report["attempts"].append(
                {
                    "spelling": "extra_body.response_format",
                    "status": "error",
                    "error": _short(exc),
                }
            )

    if resp is not None:
        report["response"] = response_json(resp)
        report["text"] = output_text(resp)
        try:
            report["parsed"] = json.loads(report["text"])
            report["valid_json"] = True
        except json.JSONDecodeError as exc:
            report["valid_json"] = False
            report["json_error"] = str(exc)

    save_json("search_structured.json", report)
    print(json.dumps(report.get("attempts"), indent=2))
    if "parsed" in report:
        print(json.dumps(report["parsed"], indent=2))


def _short(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) <= 600 else text[:600] + "..."


if __name__ == "__main__":
    main()
