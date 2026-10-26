"""Probe: object-life research on the Roelofarendsveen water tower.

Same method as probe 4, reading the Dutch article first (it is the only
Wikipedia article for Q2487636). Saves object_life_tower.json and reports
whether the history touches war or politics (demo-subject check).
"""

import json

from probes.common import client, response_json, save_json
from probes.probe_object_life import SCHEMA, build_timeline

QUESTION = (
    "What happened to the Watertoren (water tower) in Roelofarendsveen, "
    "Netherlands, itself over its lifetime: when was it built, and was it "
    "ever extended, damaged, burnt, demolished, moved, restored, repurposed "
    "or rebuilt? Give the year of each change. Start from the Dutch "
    "Wikipedia article https://nl.wikipedia.org/wiki/"
    "Watertoren_(Roelofarendsveen) and verify with other sources. State "
    "only what the sources say. Do not narrate your steps; answer with the "
    "JSON object only."
)

WAR_WORDS = ("war", "oorlog", "military", "leger", "politic", "nazi", "bezetting")


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
    war_hits = [
        e
        for e in parsed["events"]
        if any(w in (e["event"] + " " + e["detail"]).lower() for w in WAR_WORDS)
    ]
    save_json(
        "object_life_tower.json",
        {
            "question": QUESTION,
            "events": parsed["events"],
            "sources": parsed["sources"],
            "timeline": timeline,
            "citations": citations,
            "intermediate_messages": narration,
            "war_or_politics_events": [e["year"] for e in war_hits],
            "response": data,
        },
    )
    print("events:")
    for e in parsed["events"]:
        print(f"- {e['year']}: {e['event']} :: {e['detail'][:150]}")
    print("timeline:")
    for seg in timeline:
        print(f"- {seg['from_year']} to {seg['to_year']}: {seg['state']}")
    print(f"citations={len(citations)} intermediate={len(narration)}")
    print(f"sources={parsed['sources']}")
    print(f"war_or_politics_events={[e['year'] for e in war_hits]}")


if __name__ == "__main__":
    main()
