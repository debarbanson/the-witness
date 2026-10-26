# 05 Build log

Everything in this repository was built during the hackathon, from the kickoff on 26 October to 4 November 2026. One entry per day: what was built, what was proven, what changed.

## Plan (submission due Wed 4 November, 21:00 ET = Thu 5 November, 03:00 CET)

| Day | Goal |
|---|---|
| Mon 26 Oct, evening | Probes: object state research, a burnt-era painting, the vision check, the SAM base, EXIF GPS and the Overpass lookup on a real phone photo |
| Tue 27 Oct | Steps 0 to 3 as tested modules: identify, cut out, research, verify; CLI runs them on one photo |
| Wed 28 Oct | Steps 4 to 6: paint, check, layers |
| Thu 29 Oct | Step 7: the renderer; first complete film from the CLI |
| Fri 30 Oct | The web page, locally; hosting chosen and tested |
| Sat 31 Oct to Sun 1 Nov | Three demo films (windmill, tree, lighthouse); deploy the page |
| Mon 2 Nov | Hardening: limits, errors, the phone end to end, README |
| Tue 3 Nov | Freeze; record and edit the 3-minute video |
| Wed 4 Nov, daytime | Submit; post the demo on X |

## Mon 26 October (kickoff, 17:00 to 18:00 CET)

- Repository created after the kickoff.
- Foundation documents written: brief, pipeline, accuracy rules, demo plan.
- Meta's documentation read for every API the pipeline uses; open questions marked TEST in the pipeline.

## Mon 26 October, evening (day-1 probes, 17:54 to 18:00 CET)

Checklist:

- [x] One real call per model: `sam-3.1` cut-out, `muse-spark-1.3` with `web_search` returning `url_citation`, `muse-image-1.0` chained turn (at 1024x1536, not 1080x1920; see below).
- [x] TEST: `web_search` plus structured output in one call. It works.
- [x] TEST: how much Muse Image shifts framing between chained turns. Centre drift 3 to 5 percent of frame.
- [ ] Choose the three demo subjects and their photos. Windmill photo secured (CC0 De Adriaan); tree and lighthouse still open.

### What the probes showed

Project setup: `.venv` on Python 3.12, `pyproject.toml` (`openai`, `meta_sam_parser`, Pillow, `requests`, pytest), empty `witness/` package, `tests/` with 3 passing tests against a recorded SAM response, `probes/` scripts with outputs in `out/probes/` (git ignored).

Proven with real calls:

- `sam-3.1` segments the noun prompt "windmill" in the CC0 De Adriaan photo and `meta_sam_parser` decodes the mask. `object.png` (RGBA, 3648x2736) and `mask.png` saved. Box coords arrive in the sent image size (1600x1200 here), so the pipeline must scale them back to the original.
- `muse-spark-1.3` with `tools: [{"type": "web_search"}]` answers "When was the De Adriaan windmill in Haarlem built, and why?" (1779, built by Adriaan de Booys to produce cement, paint and tanbark) with 12 `url_citation` annotations. `include: ["web_search_call.results"]` returns the 11 source results.
- TEST passed: `web_search` plus structured output works in one call, using the Responses API spelling `text: {"format": {"type": "json_schema", ...}}`. The final message is pure schema JSON and still carries `url_citation` annotations. Earlier messages hold narration, so the pipeline must read the last message only.
- `muse-image-1.0` chains turns with `previous_response_id`: anchor (photo as `input_image`) then 1850 and 1950 eras. Framing and style stay consistent; the eras show correct period detail (horse carts, then cars and bicycles).
- TEST measured: SAM boxes on the three paintings show the windmill centre moves 3 to 5 percent of frame width/height between anchor and eras. SAM boxes are about 20 percent smaller in the eras, mostly because the sails are painted in a different rotation, which shrinks the bounding box. Drift is small but real, so compositing the real cut-out back over each era stays necessary.

What failed or needs correcting in `docs/02_pipeline.md`:

- `size` and `enable_image_search` are not top level parameters (400 `unknown parameter`). They must be nested in `tools: [{"type": "image_generation", "size": ..., "enable_image_search": false}]`.
- `size: "1080x1920"` is rejected (400 `unknown value`); `"1024x1792"` too. `"1024x1536"` is accepted and returns 1280x1920 PNGs. The renderer must crop width 1280 to 1080 to reach 1080x1920.
- The noun prompt "windmill" segments the sails and cap but misses the brick base. Day 2 must try a fuller prompt or the box prompt fallback before the segment step is trusted.
- The research answer narrates its tool use ("I will research...", "The direct open failed...") and two `open_page` actions failed with a null URL before the model recovered from search results. The research step needs an instruction against narration, or a strip pass. All 12 citations pointed at one Wikipedia page despite 11 results; multi source claims need testing.
