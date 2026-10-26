# 02 Pipeline

Every API fact below was read in Meta's documentation on 26 October 2026; the source page is linked. Anything marked **TEST** is not documented either way and must be proven with a real call on day one before code depends on it.

## Platform

- Base URL `https://api.meta.ai/v1`, header `Authorization: Bearer <key>`, key in `MODEL_API_KEY` ([authentication](https://dev.meta.ai/docs/authentication.md)).
- Client: the `openai` Python package with `base_url` set; it does not read `MODEL_API_KEY` by itself, so pass it explicitly ([SDKs](https://dev.meta.ai/docs/sdks.md)).
- The coding agent uses `META_API_KEY` (same key value) ([Muse Code auth](https://dev.meta.ai/docs/muse-code/auth.md)).
- Rate limits per team: Muse Spark 3,000 RPM; `muse-image-1.0` 150 RPM; `sam-3.1` 3,000 RPM ([pricing and limits](https://dev.meta.ai/docs/pricing-rate-limits.md)).
- Stack: Python 3.10+, `openai`, `meta_sam_parser`, Pillow; renderer in HTML/SVG, recorded with Playwright and ffmpeg.

## Input

One photo (JPEG/PNG), a subject noun ("windmill") and a place ("Kinderdijk, Netherlands"). Optional: an approximate construction year.

## Step 1: Cut out the object (SAM 3.1)

- `POST /v1/responses`, model `sam-3.1`, input: `input_text` with the subject noun plus `input_image` ([segmenting](https://dev.meta.ai/docs/sam/segmenting.md)).
- Output is special-token text with a box and mask per object; decode with `meta_sam_parser` ([reading output](https://dev.meta.ai/docs/sam/reading-segmentation.md)).
- Keep the largest instance, apply the mask to the original pixels, save `object.png` (RGBA) and `mask.png`.
- If the noun prompt fails, fall back to a box prompt drawn by the user (boxes and points cannot be mixed with text in one call).

## Step 2: Research (Muse Spark with web search)

- Responses API, model `muse-spark-1.3`, `tools: [{"type": "web_search"}]`, `include: ["web_search_call.results"]` ([search grounding](https://dev.meta.ai/docs/search-grounding.md)).
- Citations come back as `url_citation` annotations on `output_text` (url, title, start and end index).
- Meta notes multi-hop research is less dependable, so ask **one question per call**:
  1. When and why was it built? (anchor year)
  2. Then one question per era, for 5 to 7 eras between the anchor year and today.
- Each answer becomes a claim: `{era, year, claim, quote_span, sources[]}`. A claim with no `url_citation` is discarded.
- **TEST:** whether `web_search` and structured output (`response_format`) work in one call. If not, search first, then structure in a second call without tools.

## Step 3: Verify (agentic check)

- For each claim, a second call gets the claim and the source snippets from `web_search_call.results` and must answer `supported | unsupported | partly`, quoting the sentence that supports it.
- Only `supported` claims reach the film; `partly` claims are rewritten to what the source says.
- The same pass applies the content rules from [03_accuracy.md](03_accuracy.md): war, political events and living private persons are filtered out.
- Model: `muse-spark-1.3`; **TEST** whether `muse-wonder-1.0` (agentic, text out) gives better judgements for the extra cost.

## Step 4: Paint the eras (Muse Image, anchored)

Pattern from Meta's cookbook [Keep an image series consistent](https://dev.meta.ai/docs/cookbook/anchored-image-series.md):

- Responses API, model `muse-image-1.0`. Each era is a turn chained with `previous_response_id`, so every era sees the anchor.
- **Anchor turn:** the original photo as `input_image`, with an instruction to keep the object's position, scale and perspective and to establish the style.
- **Era turns:** the verified claims for that era describe the scene (season, surroundings, period dress and transport), plus the shared style words, `size: "1080x1920"` (sets the aspect ratio; exact output pixels are not documented, so resize afterwards).
- `enable_image_search: false`: its sources are not surfaced, so it cannot back citations, and it could pull images we hold no rights to ([image generation](https://dev.meta.ai/docs/image-generation.md)). Reference images come only from public-domain sources we pass ourselves, logged per film.
- **Pixel-exact object:** after each era is painted, `object.png` from step 1 is composited back over the same position, so the object in the film is always the real one. Align with the anchor turn's framing; **TEST** how far Muse Image shifts the composition between turns.
- A safety block returns 400 `content_policy_violation`; log it, soften the scene prompt once, otherwise skip the era.

## Step 5: People as layers (SAM 3.1)

- On each painted era, `sam-3.1` with the prompt `person` (up to 16 objects) gives masks for period figures.
- Each figure becomes its own RGBA layer, so the renderer can move them at a different speed from the background (parallax).

## Step 6: Film (our renderer)

- One HTML page per film: background, figure layers, the real object, caption and citation, each a pure function of time `t`.
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
