"""Probe 2: one grounded question to muse-spark-1.3 with the web_search tool.

Saves search_response.json (full response), search_answer.txt (the text)
and search_citations.json (the url_citation annotations) to out/probes/.
"""

import json

from probes.common import client, output_text, response_json, save_json, save_text

QUESTION = "When was the De Adriaan windmill in Haarlem built, and why?"


def main() -> None:
    resp = client().responses.create(
        model="muse-spark-1.3",
        tools=[{"type": "web_search"}],
        include=["web_search_call.results"],
        input=QUESTION,
    )
    save_json("search_response.json", response_json(resp))

    answer = output_text(resp)
    save_text("search_answer.txt", answer + "\n")

    citations = []
    for item in resp.output or []:
        for block in getattr(item, "content", None) or []:
            for ann in getattr(block, "annotations", None) or []:
                if getattr(ann, "type", None) == "url_citation":
                    citations.append(
                        {
                            "url": ann.url,
                            "title": getattr(ann, "title", None),
                            "start_index": ann.start_index,
                            "end_index": ann.end_index,
                        }
                    )
    save_json("search_citations.json", {"question": QUESTION, "citations": citations})
    print(f"answer chars={len(answer)} citations={len(citations)}")
    print(answer)
    for c in citations:
        print(f"- {c['title']} :: {c['url']}")


if __name__ == "__main__":
    main()
