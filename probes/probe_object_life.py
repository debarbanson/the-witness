"""Probe 4: research the object's own life and build its state timeline.

Asks muse-spark-1.3 with web_search what happened to De Adriaan itself
(built, damaged, burnt, rebuilt, with years), with structured output, then
derives the {from_year, to_year, state} timeline. Saves object_life.json.
"""

import json
import re

from probes.common import client, response_json, save_json

QUESTION = (
    "What happened to the De Adriaan windmill in Haarlem itself over its "
    "lifetime: when was it built, and was it ever extended, damaged, burnt, "
    "demolished, moved, restored or rebuilt? Give the year of each change. "
    "State only what the sources say. Do not narrate your steps; answer with "
    "the JSON object only."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "event": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["year", "event", "detail"],
                "additionalProperties": False,
            },
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["events", "sources"],
    "additionalProperties": False,
}

# Event keyword to the object's state from that year on, per pipeline step 2.
# Order matters: more specific words first ("rebuilt" contains "built").
STATE_AFTER = [
    (("burnt", "burned", "fire", "destroyed", "demolished"), "burnt, only the base left"),
    (("rebuilt", "reopened", "reconstructed"), "rebuilt"),
    (("restored", "renovated", "redecorated"), "restored"),
    (("built", "opened", "completed"), "standing"),
    (("extended", "extension", "steam"), "standing, extended"),
    (("damaged", "storm"), "standing, damaged"),
    (("repurposed", "converted", "conversion"), "repurposed"),
]


def main() -> None:
    resp = client().responses.create(
        model="muse-spark-1.3",
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        text={
            "format": {
                "type": "json_schema",
                "name": "object_life",
                "schema": SCHEMA,
                "strict": True,
            }
        },
        input=QUESTION,
    )
    data = response_json(resp)

    messages = [o for o in data["output"] if o.get("type") == "message"]
    last = messages[-1]["content"][0]
    parsed = json.loads(last["text"])
    citations = [
        {"url": a["url"], "title": a.get("title")}
        for a in last.get("annotations", [])
        if a.get("type") == "url_citation"
    ]
    narration = [m["content"][0].get("text", "") for m in messages[:-1]]

    timeline = build_timeline(parsed["events"])
    save_json(
        "object_life.json",
        {
            "question": QUESTION,
            "events": parsed["events"],
            "sources": parsed["sources"],
            "timeline": timeline,
            "citations": citations,
            "intermediate_messages": narration,
            "response": data,
        },
    )
    print("events:")
    for e in parsed["events"]:
        print(f"- {e['year']}: {e['event']}")
    print("timeline:")
    for seg in timeline:
        print(f"- {seg['from_year']} to {seg['to_year']}: {seg['state']}")
    print(f"citations={len(citations)} intermediate={len(narration)}")


def build_timeline(events: list) -> list:
    """Turn sorted life events into {from_year, to_year, state} segments."""
    ordered = sorted(events, key=lambda e: e["year"])
    states = [(e["year"], _state_after(e["event"], e.get("detail", ""))) for e in ordered]
    segments = []
    for i, (year, state) in enumerate(states):
        to_year = states[i + 1][0] if i + 1 < len(states) else None
        segments.append({"from_year": year, "to_year": to_year, "state": state})
    return segments


def _state_after(event: str, detail: str = "") -> str:
    words = set(re.findall(r"[a-z]+", event.lower()))
    for keywords, state in STATE_AFTER:
        if words & set(keywords):
            if state == "rebuilt" and re.search(
                r"\b(start|started|began|under way|underway|first stone|first pole)\b",
                detail.lower(),
            ):
                return "under reconstruction"
            return state
    return f"after: {event}"


if __name__ == "__main__":
    main()
