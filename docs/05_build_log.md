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

### Evening probes, continued (object state, check, SAM base, identify)

- Object life (probe 4): one call, `web_search` plus JSON schema, returns 6 events for De Adriaan (built 1779, steam engine 1865, storm damage 1930, burnt 1932, rebuild started 1999, reopened 2002) with two source URLs. Timeline derived: standing 1779 to 1865; extended to 1930; damaged to 1932; burnt, only the base left, to 1999; under reconstruction to 2002; rebuilt since. Two caveats: the "do not narrate" instruction did not stop 3 intermediate narration messages (final message is pure JSON, so read the last message only); and all 6 `url_citation` annotations point at Wikipedia while the second source (the mill's own timeline) has no positional citation.
- Burnt era plus vision check (probe 5): continuing the day-1 chain from the 1950 response id still works, and the new turn paints 1950 with only the ruined brick base, same viewpoint and style. `muse-spark-1.3` shown the painting with the verified state answers MATCHES with a correct description. Step 5 is proven in principle.
- SAM base (probe 6): "windmill with its brick base" covers more of the base but leaves it ragged and partial, so the box prompt was used: `build_object_prompt` with a hand box returns the whole mill including the base. It also takes in the two boats moored in front. Step 1 will need a tighter box or negative points on occluders.
- Identify (probe 7): on the owner's phone photo, EXIF GPS is present (DMS to 2 dp, altitude present) and the Overpass `around:300` query from step 0 works with the app User-Agent, returning 1 candidate (a memorial, 36 m). The vision pick is honestly NONE: the photo shows a floodlit building with a mural, not the memorial. No coordinates were printed or saved (verified in `identify.json`); the upload is re-encoded with EXIF stripped (asserted). Follow-ups: the tag set may be too narrow for ordinary buildings, and overpass-api.de gave two 502s on a follow-up query, so step 0 needs retry with backoff and a fallback instance.

### Step 0 redo and tower research (26 October, late evening)

- Broad Overpass query (probe 7 rerun): the key-regex form from step 0 works, returning 5 named notable things within 250 m, including `watertoren roelofarendsveen` (`man_made=water_tower`, Q2487636).
- Wikidata second source: geosearch returns 24 items, WDQS `wikibase:around` 25, both find Q2487636. WDQS works better: labels and instance types arrive in the one call, while geosearch needs a second `wbgetentities` round trip for labels.
- Sitelinks per candidate work in one batched call. The tower has a Dutch article only (`Watertoren (Roelofarendsveen)`), no English one, which is exactly why step 2 reads the local language first.
- Ranking caveat: the camera faced 201 degrees but the tower stands at bearing 5, so direction ranking put the right answer 5th of 5. The vision pick still chose it with high confidence. `GPSImgDirection` can mislead (stale compass); keep the top 5 for the pick and never cut harder on direction alone.
- Relation caveat: the Kaag en Braassem boundary relation matched `around` (its border is near) but `out center` put it 1113 m away. Step 0 must drop candidates past the radius.
- Reliability: Overpass 502 and timeouts again early on; the probe's retry plus second instance plus degrade-to-Wikidata path all ran. Wikidata answers slowly (8 to 20 s per call); allow generous timeouts. No coordinates printed or saved (verified in `identify2.json`).
- Tower object life: built 1932 (architect Sangster), decorated with tulips 1986, out of use 1987, tulips blown off 1990, new tulips 1991. No war or politics events, so it passes the demo-subject check. Citations span 2 distinct URLs (Dutch Wikipedia, Tripadvisor); the "do not narrate" instruction still left 5 intermediate messages.
- Mapper fix: `restored` is now its own state instead of `rebuilt` (the tower was redecorated, not rebuilt); both timelines re-derived without new calls.
