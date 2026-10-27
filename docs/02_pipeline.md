# 02 Pipeline

Every API fact below was read in Meta's documentation on 26 October 2026; the source page is linked. Anything marked **TEST** is not documented either way and must be proven with a real call on day one before code depends on it.

## Platform

- Base URL `https://api.meta.ai/v1`, header `Authorization: Bearer <key>`, key in `MODEL_API_KEY` ([authentication](https://dev.meta.ai/docs/authentication.md)).
- Client: the `openai` Python package with `base_url` set; it does not read `MODEL_API_KEY` by itself, so pass it explicitly ([SDKs](https://dev.meta.ai/docs/sdks.md)).
- The coding agent uses `META_API_KEY` (same key value) ([Muse Code auth](https://dev.meta.ai/docs/muse-code/auth.md)).
- Rate limits per team: Muse Spark 3,000 RPM; `muse-image-1.0` 150 RPM; `sam-3.1` 3,000 RPM ([pricing and limits](https://dev.meta.ai/docs/pricing-rate-limits.md)).
- Stack: Python 3.10+, `openai`, `meta_sam_parser`, Pillow; renderer in HTML/SVG, recorded with Playwright and ffmpeg.

## Input

One photo (JPEG/PNG) and a location. The location comes from, in order:

1. the photo's own GPS data (EXIF GPS tags, read with Pillow);
2. the browser's Geolocation API at upload time, when the photo carries none (web page only, with the user's permission);
3. a typed place name, as the last resort (and the command line's `--place`).

Privacy: coordinates are used for the lookup in step 0 only and never stored. Outputs carry no GPS data: re-encode images, never copy EXIF.

## Step 0: Identify the object

From a photo alone, "a windmill" could be any of thousands. The research needs to know which one.

1. **Nearby candidates, any kind of object.** The step never depends on what the user photographed; it gathers every named, notable thing nearby.
   - **OpenStreetMap (Overpass API):** `POST https://overpass-api.de/api/interpreter` for everything within about 250 m that has a `name` and at least one of `wikidata`, `wikipedia`, `heritage`, `historic`, `tourism` or `man_made`, for example `nwr(around:250,<lat>,<lon>)[name][~"^(wikidata|wikipedia|heritage|historic|tourism|man_made)$"~"."];` with `out tags center;`. Keep `name`, the kind tags, `wikidata` and `wikipedia`.
   - **Proven 26 Oct:** a narrow tag set (windmill, lighthouse, historic, tree) missed the owner's photo of the Roelofarendsveen water tower (`man_made=water_tower`, Wikidata Q2487636); a broader query found it. **TEST** the key-regex form above on that photo.
   - **Wikidata nearby items** as a second source, for objects OSM tags poorly. Wikidata is language-neutral: each item carries coordinates and links to its Wikipedia article in every language, so no language is hard-coded. Query items near the photo with the MediaWiki API on wikidata.org (`action=query&list=geosearch`). Avoid the Wikidata Query Service for this: its `wikibase:around` is deprecated for the new backend and the public endpoint is slow and throttled (60 s of query time per minute per client) ([WDQS manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual), [query limits](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/query_limits)). **TEST** geosearch on wikidata.org on day 2.
   - **Article languages per candidate (from the Wikidata sitelinks):** the language of the country where the photo was taken (local Wikipedias know local history best), the user's own language, and English as a fallback.
   - **Reliability:** Overpass returned 502 twice on 26 Oct. Retry with a pause (30 s after 429 or 502), then a second public Overpass instance; cache every result.
   - Fair use (OSM wiki, checked 26 Oct): under 10,000 queries and 1 GB a day, a `User-Agent` naming the app, no parallel scripts, cache results, and wait 30 s after a 429 ([Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)).
2. **Rank by distance; camera direction is a tie-breaker only.** **Proven 26 Oct:** the owner's photo said 201 degrees while the tower stood at bearing 5 (the camera was pointed upwards, where the compass is unreliable), so direction ranking put the right answer last. Rank by distance, use `GPSImgDirection` only to break ties, and drop candidates whose centre lies beyond the radius (a municipal boundary matched `around` but sat 1,113 m away). Keep the top 5; the vision pick chose correctly from them.
3. **Typed place to coordinates (Nominatim), fallback only.** At most 1 request per second, a `User-Agent` naming the app, results cached, attribution shown; no autocomplete ([usage policy](https://operations.osmfoundation.org/policies/nominatim/)).
4. **Pick the match (Muse Spark, vision).** `muse-spark-1.3` gets the photo and the ranked candidates (names, kinds, distances, bearings) and returns the best match with a confidence, or "none of these" (then the user types the name). The photo is sent re-encoded, without EXIF.
5. **Confirm with the user.** "Is this De Adriaan, Haarlem?" Yes, or a correction, before any research runs. The confirmed name, place and Wikidata or Wikipedia link (when present) seed step 2.
6. OpenStreetMap attribution ("© OpenStreetMap contributors") appears on the end card when OSM data was used.

## Step 1: Cut out the object (SAM 3.1), for the closing shot

- `POST /v1/responses`, model `sam-3.1`, input: `input_text` with the subject noun plus `input_image` ([segmenting](https://dev.meta.ai/docs/sam/segmenting.md)).
- Output is special-token text with a box and mask per object; decode with `meta_sam_parser` ([reading output](https://dev.meta.ai/docs/sam/reading-segmentation.md)).
- Keep the largest instance, apply the mask to the original pixels, save `object.png` (RGBA) and `mask.png`.
- **Proven 26 Oct:** box coordinates come back in the size of the image that was sent (downscaled to 1600 px), so scale them back to the original. The prompt "windmill" took the sails and cap but missed the brick base: try a fuller noun phrase ("windmill with its brick base") or the box fallback.
- If the noun prompt fails, fall back to a box prompt drawn by the user (boxes and points cannot be mixed with text in one call).

## Step 2: Research (Muse Spark with web search)

- Responses API, model `muse-spark-1.3`, `tools: [{"type": "web_search"}]`, `include: ["web_search_call.results"]` ([search grounding](https://dev.meta.ai/docs/search-grounding.md)).
- Citations come back as `url_citation` annotations on `output_text` (url, title, start and end index).
- Meta notes multi-hop research is less dependable, so ask **one question per call**:
  1. When and why was it built? (anchor year)
  2. **The object's own life:** what happened to the object itself (extended, damaged, burnt, demolished, moved, restored, rebuilt), with years. This gives its **state per era**.
  3. Then one question per era about its surroundings, for 5 to 7 eras between the anchor year and today.
- Each answer becomes a claim: `{era, year, kind: "object" | "surroundings", claim, quote_span, sources[]}`. A claim with no `url_citation` is discarded.
- **Structured facts first (Wikidata, free).** Before any web search, read the confirmed object's Wikidata item (`action=wbgetentities`): inception (P571), architect (P84), significant events (P793, with point in time), demolished or destroyed (P576), heritage designation (P1435), and the image and Commons category (P18, P373). Each dated statement becomes a claim whose source is the Wikidata item URL plus any references on the statement. These seed the state timeline; web search fills in and confirms.
- **Languages:** sources may be in any language; the research reads the local-language and the user's-language articles first (from step 0). Captions are written in the user's language (on the web page, from the browser's language setting; on the command line, `--lang`, default English). Source links keep their original language.
- From the object claims, build a state timeline: `{from_year, to_year, state}` where a state is what you would see standing in front of the object: a condition from a fixed list (`under_construction`, `standing`, `damaged`, `burnt`, `ruin`, `rebuilt`, `moved`, `demolished`), a degree (`partial` or `total`), a scope (`whole` or `part`), and a free sourced description of the visible change. One meaning question decides state vs caption: does this change what the object physically looks like? Non-physical history (architect, listing, rename, plans) stays as captions (for example De Adriaan: standing 1779 to 1932; ruin 1932 to 1999; under construction 1999 to 2002; rebuilt from 2002).
- **Proven 26 Oct:** `web_search` plus structured output works in one call, with the Responses API spelling `text: {"format": {"type": "json_schema", ...}}`. Read the last message only: earlier messages narrate the tool use ("I will research..."). The answer still carries `url_citation` annotations.
- Research prompts tell the model not to narrate its steps.
- In the first probe, all 12 citations pointed at one Wikipedia page; prefer claims backed by more than one source when they exist.

## Step 3: Verify (agentic check)

- For each claim, a support call gets the claim and the fetched source passages (never snippets alone) and must answer `supported | unsupported | partly`, with per-source support and the quote from the best-ranked supporting source. Support runs on the open-weights Muse Spark Open via Baseten by default, with Meta fallback per call; research, vision, the search fallback and completion stay on Meta. Web search runs only when no passage was fetched.
- A deterministic precheck (the claim's year and key words in one passage) sends an `unsupported` answer to a second confrontation judgement instead of accepting it.
- A literal quote beats a vote. When a support answer quotes a sentence that really appears in the fetched passages (checked in code after normalising whitespace and quotes) and that sentence carries the claim's year and key terms, the claim is supported with no further vote. A quoted answer is never outvoted by quoteless ones.
- Wikidata anchors the build year. An inception (P571) or official opening (P1619) date with a reference is the fixed build claim; research may add claims but never a second construction year, neither contradicting the anchor nor duplicating it. The anchor is confirmed by a sentence pairing its year with a construction word in the fetched article text (ten languages read; others fall back to a vote), so it holds on every run.
- Claims verify in film order: the build anchor first, then earliest year first, so the first scene is ready first.
- The anchor claim and every claim that would set a state get best of three, with every round kept in `research.json`; temperature 0 steadies the calls (probed 27 Oct; `seed` is not in the SDK surface).
- Completion ("did it really happen?") is asked separately, only for state-setting claims and claims whose own text raises doubt.
- Only `supported` claims reach the film; `partly` claims are rewritten to what the source says and count only through the rewrite.
- The same pass applies the content rules from [03_accuracy.md](03_accuracy.md): war, political events and living private persons are filtered out.
- Owner-reviewed research is kept per object and language, so a demo film never changes between runs; stability itself is measured with the cache off.
- Model: `muse-spark-1.3`; **TEST** whether `muse-wonder-1.0` (agentic, text out) gives better judgements for the extra cost.
- **Open-weights option (planned).** Baseten credits were requested on 26 Oct to run this verification step, and the visual check in step 5, on Meta's open-weights model Muse Spark Open (model `meta-models/muse-spark-open-1026` per the hackathon guide, not the id in Baseten's own docs; Baseten's OpenAI-compatible endpoint `https://inference.baseten.co/v1`, key `BASETEN_API_KEY`). Build `verify.py` and `check.py` with the model behind one small setting (provider, base URL, model id, key name), so switching is configuration, not code. Default: the Meta Model API. This targets the "Best Build on Meta Open Weight Models" prize.

## Step 3a: Choose the scenes

A 40 to 60 second film holds at most 7 scenes of 6 to 8 seconds. When there are more verified periods, choose:

1. Every period in which the object itself changed state (built, extended, decorated, damaged, burnt, restored, rebuilt, repurposed): these carry the story.
2. Then the periods with the strongest verified surroundings claims, spread across the timeline.
3. Today, closing on the user's photo, always last.

Merge or drop the rest. The captions of dropped periods may still appear as a short line inside a neighbouring scene ("in 1802 I was sold and ground tobacco"), but never get a painting of their own. The chosen scenes and the reason for each are kept in `research.json`.

## Step 3b: Enough for a film?

Never fill a gap by inventing. After verification, count what is left and choose the outcome:

| Outcome | Needs | What the user gets |
|---|---|---|
| **Full film**, 40 to 60 s | Object confirmed; build year or first mention sourced; at least 5 verified claims across at least 4 eras; at least 2 distinct good sources | The film as designed |
| **Short film**, 20 to 30 s | At least 3 verified claims across 2 or 3 eras | A shorter film that says so: "Little is written about me, but this is certain." |
| **Too little for a film** | Fewer than 3 verified claims | No film. One card with the verified facts and their sources, and two ways forward (below) |
| **Not identified** | Step 0 found no match and the user's name for it finds nothing | An honest message; never a film about the wider area presented as the object |

Ways forward when there is too little:

- **Add a source.** The user pastes a link (a local history society, a municipal page). It goes through steps 2 and 3 like any other source, and the outcome is recounted.
- **Tell what you know.** The user records or types what they know. A recording is transcribed with `muse-voice-transcribe-1.0` (`POST /v1/asr/transcribe`). It is shown labelled "told by <name>", never as a verified fact, and never counted towards the thresholds above.

The thresholds are first guesses; tune them on the demo subjects.

## Step 4: Paint the eras (Muse Image, anchored)

Pattern from Meta's cookbook [Keep an image series consistent](https://dev.meta.ai/docs/cookbook/anchored-image-series.md):

- Responses API, model `muse-image-1.0`. Each era is a turn chained with `previous_response_id`, so every era sees the anchor.
- **Parallel eras (TEST for speed).** Painting eras one after another, each chained on the previous, takes about 3 minutes for 7 eras. Instead, branch every era from the anchor turn (`previous_response_id` = the anchor's id) and paint them in parallel (the limit is 150 images a minute). Consistency then rests on the anchor alone: measure object drift and style against the serial chain on De Adriaan before switching.
- **Anchor turn:** the user's photo as `input_image`, with an instruction to keep the place's viewpoint and composition and to establish the painted style.
- **Era turns:** the object's verified state for that year (from the state timeline) plus the verified surroundings (season, period dress and transport) and the shared style words. The object is painted as it was then: whole, burnt, a stump, under scaffolding, rebuilt.
- **Settings go inside the image tool** (proven 26 Oct; top-level parameters return 400 `unknown parameter`): `tools: [{"type": "image_generation", "size": "1024x1536", "enable_image_search": false}]`. `"1080x1920"` and `"1024x1792"` are rejected; `"1024x1536"` returns 1280x1920, which the renderer crops to 1080x1920.
- `enable_image_search: false`: its sources are not surfaced, so it cannot back citations, and it could pull images we hold no rights to ([image generation](https://dev.meta.ai/docs/image-generation.md)).
- **Historical reference images (free; public domain, CC0 or CC BY).** A real photo of the object from an earlier era makes that era's painting far more accurate, and it becomes a source the film can show ("painted from a photograph of 1935").
  - **Wikimedia Commons:** the files in the object's Commons category (Wikidata P373) and its main image (P18), via the MediaWiki API (`prop=imageinfo&iiprop=url|extmetadata`). Use a file only if its licence is public domain, CC0 or CC BY (`LicenseShortName` in extmetadata; keep `Artist` and `LicenseUrl` for the credit), and take its date from the metadata.
  - **Europeana** (European collections): the Search API with a free key (`wskey`, in `.env.local` as `EUROPEANA_API_KEY`) and `reusability=open`, keeping only items whose rights statement is public domain (PDM), CC0 or CC BY. **Proven 26 Oct:** `reusability=open` also returns CC BY-SA, so the rights filter must run in our code on every item. Europeana may limit heavy use (HTTP 429), and keys may not be shared. Keys are personal: the owner registers for one.
  - Each reference is passed as an `input_image` on the era turn whose date it matches, and logged in `sources.md` with its URL, date and licence.

## Free sources, and their rules

Every source outside the Meta API is free. They ask for good manners, which the code must follow:

| Source | Used for | Key | Rules |
|---|---|---|---|
| OpenStreetMap Overpass | Nearby candidates | None | User-Agent naming the app, under 10,000 queries a day, no parallel calls, cache, 30 s pause after 429 |
| Nominatim | Typed place to coordinates | None | At most 1 request per second, User-Agent, cache, attribution, no autocomplete |
| Wikidata and Wikipedia (MediaWiki API) | Nearby items, structured facts, articles | None | User-Agent with contact details, one request at a time, cache, back off on `ratelimited` ([etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)) |
| Wikimedia Commons | Historical reference images | None | As Wikidata; public domain, CC0 or CC BY files only, CC BY credited by author, licence and link |
| Europeana | Historical reference images | Free personal key | A personal key is for "individual, non-production use": use it for building and for the demo films; the public web page uses Commons only unless a Europeana project key is granted. Key never shared or committed. All API use is logged; reasonable limits (429). Use each image only as its own `edm:rights` statement allows (public domain, CC0 or CC BY here), keep its rights URL and provider link with it, credit the provider, and remove an image on Europeana's request ([terms of use](https://www.europeana.eu/en/rights/terms-of-use)) |

The User-Agent for all of them: `the-witness/0.1 (https://github.com/debarbanson/the-witness)`. Wikimedia's policy accepts a website as the contact, so no email address goes into public code.
- **Consistency, measured 26 Oct:** between chained turns the object's centre moved 3 to 5 percent of the frame. Small enough for crossfades; the renderer can align eras on the SAM box of the object in each painting.
- A safety block returns 400 `content_policy_violation`; log it, soften the scene prompt once, otherwise skip the era.

## Step 5: Check each painting against the object's state (Muse Spark, vision)

- Each painted era goes to `muse-spark-1.3` as `input_image` with the object's verified state for that year, and the question: does the painting show the object in that state? Answer `matches | differs`, with what differs.
- `differs` triggers one repaint with the difference spelled out; a second `differs` drops the era and logs why.
- This is the visual half of "no source, no claim": what the film shows of the object is checked, not only what it says.

## Step 5b: Spot the difference (children's version)

One painted era next to today's photo; `muse-spark-1.3` (vision) finds up to 5 visible differences with regions, each checked against what is visible and against the object's verified state. Full specification, and the children's captions and painting style: [08_children.md](08_children.md). The audience setting (`adult` or `child`) runs through steps 2 to 7; both versions are made together and cached.

## Step 6: People as layers (SAM 3.1)

- On each painted era, `sam-3.1` with the prompt `person` (up to 16 objects) gives masks for period figures.
- Each figure becomes its own RGBA layer, so the renderer can move them at a different speed from the background (parallax).

## Step 7: Film (our renderer)

- One HTML page per film: background, figure layers, caption and citation, each a pure function of time `t`.
- The closing shot is the user's own photo as "today": the last painted era dissolves into it, using the SAM cut-out from step 1 to bring the object in first.
- **The film plays in the browser, live.** The page is the film: every frame is a pure function of `t`, so the web page plays it directly the moment the last painting is checked, with no rendering wait.
- **MP4 only for download or sharing**, made in the background when asked: Playwright steps `t` frame by frame at 30 fps and captures 1080x1920 frames; ffmpeg encodes H.264 MP4.
- Structure: title card (object, place) → anchor year → one era per 6 to 8 seconds with slow push-in and crossfade → today (the user's original photo) → end card with all sources and the AI-imagery label.
- Captions are first person from the object, written from verified claims only, max 2 lines each.

## Time budget per film

A visitor will not watch a spinner for minutes, but will wait about two minutes if every few seconds brings something worth seeing. Targets (our judgement, to be measured; step timings are logged per object):

| Moment | What the user sees | Target |
|---|---|---|
| Object recognised | "Is this De Adriaan, Haarlem?" | within 15 s |
| The story | The verified timeline, each fact with its source, readable while the rest is made | within 60 s of confirming |
| The paintings | Eras appear one by one in the timeline | first within 90 s, all within 2 min |
| The film | Plays in the browser | within 2 to 3 min of confirming |
| Any moment | Never more than 10 to 15 s without visible progress | always |

How the budget is met:

- **Research and verify in 60 to 90 s:** choose the scenes before verifying, verify in parallel, lighter reasoning for checks, cache (steps 2, 3 and 3a).
- **Paint in 30 to 60 s:** parallel eras branched from the anchor (step 4), checks in parallel (step 5).
- **No rendering wait:** the film plays in the browser; MP4 only on request (step 7).
- **Cache per object:** a researched and painted object (Wikidata id plus language) is kept, so the next visitor of the Eiffel Tower gets the film at once. For the demo, famous objects open instantly, while a judge's own photo runs live.

## Cost per film (estimate from the published prices)

| Item | Count | Cost |
|---|---|---|
| Web searches | ~12 | ~$0.03 |
| Muse Spark tokens | ~150k in, ~20k out | ~$0.27 |
| Muse Image | ~8 images | ~$0.08 |
| SAM 3.1 | ~10 images | ~$0.03 |
| **Total** | | **under $0.50** |

## Output layout

```
out/<slug>/
  object.png  mask.png
  research.json       claims with sources and verdicts
  eras/<n>.webp       painted eras, raw
  layers/<n>/*.png    figure layers
  film.mp4  sources.md
```
