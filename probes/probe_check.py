"""Probe 5: paint 1950 with the object in its verified state, then check it.

Continues the day-1 image chain (previous_response_id of the 1950 turn):
the mill burnt down in 1932, so in 1950 only the brick base is left.
Then muse-spark-1.3 looks at the painting as input_image with that state
and answers "matches" or "differs". Saves era_1950_burnt.png,
image_1950_burnt.json and check_1950_burnt.json.
"""

import base64
import json

from probes.common import OUT, client, data_uri, response_json, save_json
from probes.probe_image import _tools

STATE_1950 = (
    "The De Adriaan windmill burnt down completely on 23 April 1932. "
    "In 1950 only its round brick base is left standing on the Spaarne bank: "
    "no cap, no sails, no smock. Verified state: burnt, only the base left."
)


def main() -> None:
    prev = json.loads((OUT / "image_1950.json").read_text())["id"]
    api = client()

    resp = api.responses.create(
        model="muse-image-1.0",
        tools=_tools(),
        previous_response_id=prev,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Repaint this exact view in the year 1950, same "
                            "viewpoint and painted style as the series. This "
                            "time the verified history changes the object: "
                            + STATE_1950
                            + " Show the empty brick base on the river bank, "
                            "1950s surroundings otherwise (motorboats, "
                            "bicycles, vintage cars, people in 1950s dress). "
                            "Do not show a whole windmill."
                        ),
                    }
                ],
            }
        ],
    )
    data = response_json(resp)
    save_json("image_1950_burnt.json", data)
    for item in data["output"]:
        if item.get("type") == "image_generation_call" and item.get("result"):
            (OUT / "era_1950_burnt.png").write_bytes(
                base64.b64decode(item["result"])
            )
            print(f"saved era_1950_burnt.png id={data['id']}")

    uri, _ = data_uri(OUT / "era_1950_burnt.png", max_dim=1024)
    check = api.responses.create(
        model="muse-spark-1.3",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Verified state of the object in this painting: "
                            + STATE_1950
                            + " Look at the painting. Does it show the "
                            "windmill in that state? Answer with the single "
                            "word MATCHES or DIFFERS first, then one "
                            "sentence saying what you see."
                        ),
                    },
                    {"type": "input_image", "image_url": uri},
                ],
            }
        ],
    )
    check_data = response_json(check)
    save_json("check_1950_burnt.json", check_data)
    for item in check_data["output"]:
        if item.get("type") == "message":
            print("check:", item["content"][0]["text"][:400])


if __name__ == "__main__":
    main()
