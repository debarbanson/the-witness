# 05 Build log

Everything in this repository was built during the hackathon, from the kickoff on 26 October to 4 November 2026. One entry per day: what was built, what was proven, what changed.

## Plan (submission due Wed 4 November, 21:00 ET = Thu 5 November, 03:00 CET)

| Day | Goal |
|---|---|
| Mon 26 Oct, evening | Probes: object state research, a burnt-era painting, the vision check, the SAM base, EXIF GPS and the Overpass lookup on a real phone photo |
| Tue 27 Oct | Steps 0 to 3 as tested modules: identify, cut out, research, verify; CLI runs them on one photo |
| Wed 28 Oct | Steps 4 to 6: paint, check, layers; children's captions (re-verified) and picture-book style (docs/08_children.md) |
| Thu 29 Oct | Step 7: the renderer with the audience setting; spot the difference (step 5b); first complete film, adult and children's, from the CLI |
| Fri 30 Oct | The web page, locally, with the adults/children switch and the spot-the-difference game; hosting chosen and tested |
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

### Open sources probe (26 October, night)

- Wikidata facts (Q2487636): the item is sparse, only architect (Hendrik Sangster, referenced as imported from the Dutch Wikipedia), heritage designation (gemeentelijk monument, no reference) and the main image P18. No inception, no significant events, no Commons category. Structured facts seed the research but cannot replace web search for this object.
- Commons: with no P373, the probe followed P18 to Category:Watertoren (Roelofarendsveen): 4 files, all skipped (CC BY 2.0, CC BY-SA 2.5, 3.0, 4.0). The P18 file itself is CC BY-SA 2.5. Zero usable tower photos on Commons under the PD or CC0 rule.
- Europeana: the tower query returns exactly 1 result, the known CC BY-SA 3.0 photo, correctly skipped. The place query returns 271 results, all fetched; 146 kept (101 CC0, 45 PDM), 125 skipped, every skip a CC BY-SA 3.0 licence. Two lessons: `reusability=open` still returns CC BY-SA, so client-side rights filtering is mandatory; and dates are sparse (4 of 146 dated). Of the kept, 101 are Naturalis specimens (irrelevant) and none depicts the tower.
- Best dated image per era for the tower's film: 1932 to 1986 gets 4 dated references, all 1955 windmill photos from the National Archives (surroundings, not the tower); every other era gets none. The film can ground its 1950s surroundings in real photos, but no era gets a historical photo of the tower itself.
- Manners kept: the doc User-Agent on every call, sequential requests with pauses, 429 or 502 retry, raw responses saved in `out/probes/` as the cache. The identify probe's User-Agent was updated to the doc form.

### Steps 0 to 3b as tested modules (26 October, evening)

- Built `witness/identify.py`, `segment.py`, `research.py`, `verify.py`, `outcome.py` plus `models.py` (one setting per model-using step: provider, base URL, model id, key name; verify defaults to Meta `muse-spark-1.3`, switchable to Baseten `meta-models/muse-spark-open-1026` by configuration) and a shared `witness/web.py` (User-Agent, MediaWiki backoff on `ratelimited`/`maxlag`). 64 tests pass; API calls sit behind injectable transports with recorded fixtures, no live calls in tests.
- CLI: `python -m witness identify <photo>` and `python -m witness research <photo>` (`--place` fallback, `--yes` to skip confirmation). Research prints claims with sources and verdicts, the timeline and the step 3b outcome, and saves `research.json` (verified free of coordinates).
- End to end: the owner's photo identifies as the water tower (18 m, Q2487636) and researches to `short_film` (4 verified, 4 eras, 3 good sources); De Adriaan via `--place "De Adriaan Haarlem"` researches to `full_film` (6 verified, 4 eras, 3 good sources). The `not_identified` path was exercised with place strings Nominatim does not know.
- Findings from the runs: `web_search_call.results` snippets came back empty (all 65 in the recorded fixture), so verify reads Wikipedia extracts instead (non-Wikipedia sources still unfetched, a known limitation); lead-only extracts mark some true details unsupported; the state mapper gained `decorated` and Dutch `brand`. Wikidata claims now carry event words so the timeline reads cleanly.

### Review fixes before painting (26 October, night)

- Verify reads full texts: Wikipedia full articles in their own language plus plain-GET pages with main-text extraction, all cached; the verifier gets the paragraphs mentioning the claim's year or key words, and a web_search tool for what the passages do not settle, recording the quote's URL. The four review facts now verify supported: De Adriaan 1865 steam engine, 1930 storm, 1999 rebuild start, and the tower's 1990 storm. Honest footnote: the storm detail exists online only on Tripadvisor, so that quote is weak-sourced; the claim still passes quality through its Wikipedia source.
- Timeline: one segment per distinct year with adjacent equal states merged, planned-but-prevented changes skipped (1925 demolition), reconstruction kept (1999 to 2002), readable states ("decorated with tulips", Dutch `tulp` handled).
- Language: Wikidata labels in the user's language (`--lang`, default English) with English fallback; research reads the user's-language article first.
- Source quality: place and booking aggregators (AroundUs, GetYourGuide, Viator and others) count as weak like review sites, in code and in `docs/03_accuracy.md`.
- Re-ran both: tower `full_film` (5 verified, 5 eras), De Adriaan `full_film` (14 verified, 12 eras). 80 tests pass.

### Second review, test set and re-run (26 October, night)

Accuracy (all test first, 110 tests pass):
- A1 quality from the supporting source: `verify_claim` records per-source support with quotes, judges quality on supporting sources only, prefers a good-source quote, drops weak-only claims with `weak sources only`. Tower 1990 storm now unsupported as designed.
- A2 plans are not events: the verifier marks `completed:false` for planned, promised or attempted changes and `build_timeline` skips them. Eiffel 1967 move proposal is caption-only, never a state. But De Adriaan 1963 ("promise fell into oblivion") still came back completed:true, so the mill wrongly shows restored 1963-1999 (P3 in docs/07_test_set.md).
- A3 step 3a: `scenes.choose_scenes` keeps at most 7 scenes (state changes first, today last), dropped periods become caption lines on neighbours, reasons stored in `research.json`. Holds on all 12 objects.

Speed: choose-before-check (candidate scenes plus 4 spares verified, not every claim), `verify_all` in parallel over 6 workers, `reasoning.effort=low` for verify and vision calls via `models.respond`, Wikidata and source-text cache in `out/cache/`, per-step timings in every run. Brooklyn research fell from ~10 min to 115 s.

Bugs: Nominatim retries with backoff, 20 s per try, clear failure message (christ-redeemer identifies cleanly); qid slugs for every script (`q1196460-kintai-bridge`, no more `film`); `--lang` decides the user language for labels, though nl articles are still fetched everywhere (P8).

Test set: 10 Commons photos (CC0, PD or CC BY, file pages and licences in docs/07_test_set.md) plus De Adriaan and the tower, all 12 re-ran clean: 10 full films, Brooklyn short (its 1883 built claim was never checked, P7), tower too_little (1 verified; it flaps between runs, P1, and 1986 tulips was a verifier false negative, P2).

Time budget: identify misses 15 s everywhere (31-98 s); the 60 s story holds for eiffel and the tower only, with source fetching (90 s timeout, P12) the budget killer; 7 of 12 met 2-3 min research. Full timings and 15 open problems in docs/07_test_set.md.

Children's fit (no build): `research.json` scenes plus caption lines, quotes and verdicts already carry what child captions need; the audience setting will run research, captions, paint, check and renderer per docs/08_children.md.

## 27 October

Baseten credits granted ($100). Docs read (hackathon model name is meta-models/muse-spark-open-1026, not the muse-spark-open in their docs):
- https://docs.baseten.co/quickstart
- https://docs.baseten.co/reference/inference-api/chat-completions
- https://docs.baseten.co/inference/model-apis/reasoning
- https://docs.baseten.co/inference/model-apis/vision
- https://www.baseten.co/pricing ($1.25 per M input and output tokens for Muse Spark Open)
- https://dev.meta.ai/docs/pricing-rate-limits ($1.25 in, $4.25 out for Muse Spark standard; web search $2.50 per 1000 queries)

Probes: the -1026 name works with the hackathon key; reasoning arrives in `reasoning_content`, the answer in `content`; usage is reported (reasoning counts as output tokens). First call took about 10 min (cold start), later about 2 s. Meta Responses accepts `temperature=0` (used for verify calls) but the SDK has no `seed` parameter.

Comparison (identical jobs, `--verify-with both`): 6/6 regressions agree; 127/133 over the 12 objects (95.5%). False negatives symmetric (Open missed Eiffel 1887, Meta missed Biosphere 1967, both quoting the evidence). Verify time 750 s meta vs 797 s open. Support checks now default to Baseten with per-call Meta fallback (180 s timeout); research, vision, search fallback and completion stay on Meta. Details in docs/07_test_set.md.

Block 5 (P14 plus re-run): war/politics-only claims become caption lines, never scenes (test first). All 12 re-ran cache-off on the Baseten default: 10 full, 2 short (Eiffel, tower), zero failures. Local languages read everywhere (da, ja, fr, pt, nl, ca, es, it across the set). Fetch fixed (1 to 129 s, was 300 s); identify misses 15 s on all 12 because Overpass is dead from this network (60 to 90 s of timeouts, zero candidates); verify now dominates (best-of-three over a reasoning model). Ruin 1932-1999 and no 1963 held; tulips verify via nl; no designation/filename/architect states anywhere.

Stability: de-adriaan 4/4 full, tower 3/3 short after a Wikidata window failed the first three tower attempts, but details are not identical (reworded claims, supported/partly flips, 1865 standing/rebuilt 2-2). New problems: P16 partly-blank-event misclassifies conditions (2002 burnt, 1674 ruin, 1899-1953 and 1514-1845 under_construction); P17 Overpass dead; P18 identify has no redundancy; P19 distance-only top-5 cuts the true object (Heidelberg honest NONE, Colosseum confidently films the metro station); P20 vision NONE despite correct candidates (Vasa 3/3).

6 new objects: 3 full (Sagrada Familia with Catalan first, Atomium trilingual, Colosseum about the wrong object), 1 short (Belem), 2 not identified (Vasa, Heidelberg). Full report in docs/07_test_set.md. 198 tests green. Painting starts tomorrow; P16 must be fixed first.

Afternoon (Blocks A to E): all test-first, 288 tests green.

States: P16 fixed (completed partly claims keep their event; De Adriaan 2002 rebuilt, Kintai 1674 rebuilt, no 54-year construction); implausible spans flagged, never painted silently (fired live on mont 1834 and sultan 1912); P10 ranges end to end including surroundings scenes ("about 800 to 1,200 years old"); P23 moved contents, P24 moved occupants (new, assembly/congregation), P25 ruler moves, taken artefacts and outlying structures (new, borobudur and sultan cases); absurd years dropped (no more -569997974).

Identify: P19 quality ranking (sitelinks, kind, name match, top 10 plus nearest three, part folding); vision sees kinds plus descriptions with real P31 kinds; second look grounded with place and distance, veto needs two NOs; P18 retries plus wpgeo redundancy; P17 Overpass optional on 5 s; geocode takes five Nominatim hits by importance with 1 km typed-place radius; bogus EXIF falls back to the typed place, still vision gated; failure logs keep sub-timings; NONE keeps a fixed message with the model words in a progress event.

Verify and speed: best of three stops on first-two agreement; only film claims plus spares verified; Baseten 10 workers; extracts fail fast (30 s, 2 tries), no refetch across phases, reference tails trimmed, 8 plain workers; failures plus provider recorded in research.json. Fetch fixed for good (heidelberg 562 s to 3.8 s). Story still misses 60 s everywhere (verify 39 to 115 s dominates); identify meets 15 s on 4 of 13 with 4 near.

Runs (cache off): r6 four full (oak, rubjerg, heidelberg 24 claims, atomium) plus christ NONE then r7 full statue film; vasa honest NONE (diorama photo, polar EXIF); fresh six 5 full plus hungarian short then full on retry (institution label on thin sources, building content); loc2 GPS spots 20/23 correct with 0 wrong (eiffel and djenne fixed, colosseum 3/3). Wrong-object count filmed: 0. Stability on the new metric: UNSTABLE on both (same skeletons, flapping middle scenes; research wording plus verify verdict variance, dissected in docs/07_test_set.md); per-object 7-day cache covers revisits. P18 partly open (transient all-empty windows, one Wikidata geosearch outage); P20 partly open (christ flaps to honest NONE); P1 open. No painting blocker that silently mistates. Two fresh file pages still to confirm (EXIF credits recorded).

## 28 October

Block 1 (fast verify): literal-quote fast path (a quoted sentence really in the source, year plus keyword, skips the vote and outvotes quoteless verdicts); Wikidata P571/P1619 build anchor confirmed by an article sentence, no second construction year from research; film-order jobs (anchor first, then chronological) with per-claim streaming verdicts. 61 of 159 claims (38%) decided without a vote; verify wall time 30 to 105 s (was 43 to 132 s): the parallel tail still sets the time. De Adriaan anchor fires live (1779 fixed, 6 of 9 claims fast).

Block 2 (streaming): opening card from the anchor only (printed before research: 18.2 s, was 79.1 s), speculative gather during confirm with discarded cost logged, scenes verified in film order with flush, buffer playback from measured rates, scene numbers follow film order. Timed on De Adriaan cache-off: card 18.2 s, first scene 80.0 s, film ready 162.7 s. Doc section "Streaming (28 Oct)" in docs/02_pipeline.md.

What the b1 batch exposed (fixed, test-first): cirrussearch-too-busy-error (HTTP 200, ~60% of geosearch calls that evening) returned empty candidate lists; now a retried code with 5 s backoff, nearby tries 2 to 3, WP budget 10 to 15 s, source failures print as notes, _budgeted reports everything. Duplicate claims crashed Eiffel (KeyError verdict); keep_quality drops exact dupes. 333 tests green.

Batch (cache off): 11 full plus tower short, zero failures after re-runs, wrong-object count 0. Identify meets 15 s on 5 of 12. Stability: De Adriaan 3 for 3 identical on current code; tower unstable (short/short/full/too_little, Dutch scene labels under --lang en, "1931 to 1932" range build). Few-claim objects flap hardest. 60 s batch story missed everywhere (79 to 188 s); streaming measures are the answer.

Evening (Blocks 3 to 5 plus stretch, all test-first, 389 tests green).

Docs: Meta image docs checked before painting (https://dev.meta.ai/docs/image-generation plus the anchored-series cookbook): previous_response_id chaining, size sets aspect only, no seed (named as an unknown top-level field), $0.01 per image. Matches the day-1 probes.

Block 3: witness/paint.py (anchor plus chain or parallel branching, per-scene check loop, safety soften, contact sheets) and witness/check.py (matches or differs, unparseable counts as differs). De Adriaan paint-off on kept research: parallel wins (6/6 in 79 s, 0.3% drift) over chain (5/6 in 195 s, 3.6% drift, one expired-id death).

Block 4: tower 2/3 (1932 rightly dropped: tulips 54 years early), oak 6/6, Rubjerg 6/6, all contact sheets reviewed. Anchor contamination noted (tulips, snow, paragliders inherited; only the object is checked). Safety filter proven flaky on fire and harm (1932 2/9, 1870 0/9): remains framing, harm lines cut from prompts only (1982 recovered live), block retry before drop. Baseten vision check agrees 6/6; check stays on Meta.

Additions 1 and 2: film --paint verifies the anchor early and paints scene 1 during research (De Adriaan first painted 54.4 s, target met); final-choice scenes paint late (Brooklyn proof); playback sim per object (no pauses simulated; one live pause at De Adriaan 1932 from filter retries). Wikimedia timeouts bounded (15 s per try). Brooklyn stream film: 4/6 chosen painted.

Block 5: Parliament swapped for the Chain Bridge (CC0, full film, war rule clean); Hallgrimskirkja CC BY 4.0 confirmed; cost per film about $0.30 story-only, $0.47 painted, plus Baseten tokens.

Stretch: children captions 5/5 lines plus 3/6 states for De Adriaan (drops honest); 22 figure layers across 4/6 eras, one viewed clean.

Noted for Monday: research from the local article plus Wikidata first (few-claim flap), Dutch scene labels, the "1931 to 1932" range build, range-year scenes that never paint, fire-state filter hostility.

## 29 October (renderer day)

Block 1 (painting fixes, test-first): prompts ban all lettering and the check fails text or dates; one vision call judges object state plus text plus anachronisms, with differs notes feeding repaints; one anchor look per run sets the series season and the temporary elements each era holds back unless verified words up to its year name them (states describing foliage overrule the season). Repaints from kept research: De Adriaan 5/6 (1932 filter), oak 6/6, Rubjerg 6/6, tower 3/3 with the 1932 tulips gone first try. New sheets beside the old (eras_parallel_b1). Notable: the oak's bare 2026 is its verified death in June 2026, so the season rule rightly leaves it; the De Adriaan 1932 crane came from its own anchor photo.

Block 2 (renderer, step 7): witness/render builds a live page per film (title and anchor cards over the photo, 7 s eras with push-in and crossfade, first-person two-line captions with source sites, parallax figure layers, cut-out-first today dissolve, end card with sources, AI label, OSM and photo credits). Every frame is a pure function of t: the page plays live and Playwright steps the same render(t) at 30 fps into ffmpeg H.264 1080x1920 (browser needs an unsandboxed run on this Mac). Buffer progress line and clock included. Films: De Adriaan 51 s, oak 58 s, Rubjerg 58 s, page plus MP4 in out/<slug>/film/.

Block 3 (docs): parallel branching with measured reasons replaces chaining in the brief, README and step 4; Muse Wonder dropped from README; demo carries the tower tulips story and the delivery numbers; brief success criteria recorded met.
