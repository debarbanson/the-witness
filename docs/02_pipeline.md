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
   - **Wikidata nearby items** as a second source, for objects OSM tags poorly. Wikidata is language-neutral: each item carries coordinates and links to its Wikipedia article in every language, so no language is hard-coded. Query items with coordinates near the photo (MediaWiki `list=geosearch` on wikidata.org, or the Wikidata Query Service `wikibase:around`). **TEST** which of the two works best on day 2.
   - **Article languages per candidate (from the Wikidata sitelinks):** the language of the country where the photo was taken (local Wikipedias know local history best), the user's own language, and English as a fallback.
   - **Reliability:** Overpass returned 502 twice on 26 Oct. Retry with a pause (30 s after 429 or 502), then a second public Overpass instance; cache every result.
   - Fair use (OSM wiki, checked 26 Oct): under 10,000 queries and 1 GB a day, a `User-Agent` naming the app, no parallel scripts, cache results, and wait 30 s after a 429 ([Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)).
2. **Rank by where the camera pointed.** Photos often carry `GPSImgDirection` (the owner's: 201 degrees). Compute each candidate's bearing from the photo; candidates within about 35 degrees of the view direction rank first, then by distance. Keep the top 5.
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
- **Languages:** sources may be in any language; the research reads the local-language and the user's-language articles first (from step 0). Captions are written in the user's language (on the web page, from the browser's language setting; on the command line, `--lang`, default English). Source links keep their original language.
- From the object claims, build a state timeline: `{from_year, to_year, state}` (for example De Adriaan: standing 1779 to 1932; burnt, only the base left 1932 to 2002; rebuilt from 2002).
- **Proven 26 Oct:** `web_search` plus structured output works in one call, with the Responses API spelling `text: {"format": {"type": "json_schema", ...}}`. Read the last message only: earlier messages narrate the tool use ("I will research..."). The answer still carries `url_citation` annotations.
- Research prompts tell the model not to narrate its steps.
- In the first probe, all 12 citations pointed at one Wikipedia page; prefer claims backed by more than one source when they exist.

## Step 3: Verify (agentic check)

- For each claim, a second call gets the claim and the source snippets from `web_search_call.results` and must answer `supported | unsupported | partly`, quoting the sentence that supports it.
- Only `supported` claims reach the film; `partly` claims are rewritten to what the source says.
- The same pass applies the content rules from [03_accuracy.md](03_accuracy.md): war, political events and living private persons are filtered out.
- Model: `muse-spark-1.3`; **TEST** whether `muse-wonder-1.0` (agentic, text out) gives better judgements for the extra cost.

## Step 4: Paint the eras (Muse Image, anchored)

Pattern from Meta's cookbook [Keep an image series consistent](https://dev.meta.ai/docs/cookbook/anchored-image-series.md):

- Responses API, model `muse-image-1.0`. Each era is a turn chained with `previous_response_id`, so every era sees the anchor.
- **Anchor turn:** the user's photo as `input_image`, with an instruction to keep the place's viewpoint and composition and to establish the painted style.
- **Era turns:** the object's verified state for that year (from the state timeline) plus the verified surroundings (season, period dress and transport) and the shared style words. The object is painted as it was then: whole, burnt, a stump, under scaffolding, rebuilt.
- **Settings go inside the image tool** (proven 26 Oct; top-level parameters return 400 `unknown parameter`): `tools: [{"type": "image_generation", "size": "1024x1536", "enable_image_search": false}]`. `"1080x1920"` and `"1024x1792"` are rejected; `"1024x1536"` returns 1280x1920, which the renderer crops to 1080x1920.
- `enable_image_search: false`: its sources are not surfaced, so it cannot back citations, and it could pull images we hold no rights to ([image generation](https://dev.meta.ai/docs/image-generation.md)). Reference images come only from public-domain sources we pass ourselves, logged per film.
- **Consistency, measured 26 Oct:** between chained turns the object's centre moved 3 to 5 percent of the frame. Small enough for crossfades; the renderer can align eras on the SAM box of the object in each painting.
- A safety block returns 400 `content_policy_violation`; log it, soften the scene prompt once, otherwise skip the era.

## Step 5: Check each painting against the object's state (Muse Spark, vision)

- Each painted era goes to `muse-spark-1.3` as `input_image` with the object's verified state for that year, and the question: does the painting show the object in that state? Answer `matches | differs`, with what differs.
- `differs` triggers one repaint with the difference spelled out; a second `differs` drops the era and logs why.
- This is the visual half of "no source, no claim": what the film shows of the object is checked, not only what it says.

## Step 6: People as layers (SAM 3.1)

- On each painted era, `sam-3.1` with the prompt `person` (up to 16 objects) gives masks for period figures.
- Each figure becomes its own RGBA layer, so the renderer can move them at a different speed from the background (parallax).

## Step 7: Film (our renderer)

- One HTML page per film: background, figure layers, caption and citation, each a pure function of time `t`.
- The closing shot is the user's own photo as "today": the last painted era dissolves into it, using the SAM cut-out from step 1 to bring the object in first.
- Playwright steps `t` frame by frame at 30 fps and captures 1080x1920 frames; ffmpeg encodes H.264 MP4.
- Structure: title card (object, place) → anchor year → one era per 6 to 8 seconds with slow push-in and crossfade → today (the user's original photo) → end card with all sources and the AI-imagery label.
- Captions are first person from the object, written from verified claims only, max 2 lines each.

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
