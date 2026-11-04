# The Witness

One photo of something old. A short film of the decisive eras it lived through.

Point The Witness at a windmill, an old tree or a lighthouse. It works out which object the photo shows, researches its history on the web, checks every claim against the fetched sources, then paints the decisive eras it lived through: the world around it, and the object itself as it was then, built, damaged, rebuilt, as the sources say. Changes are shown only where an accepted, sourced claim supports them; that is what the sources support, not a guarantee of historical truth. Your own photo closes the film, dated with its own photo year. The result is a vertical film of about 30 to 37 seconds, told in the first person by the object, where every caption carries its source.

A heritage group can prepare a reviewed film per monument and link it from a QR plaque or the heritage register. Visitors point their phones at the plaque and watch what the place witnessed, with every fact linked to its source.

> De Adriaan, 23 April 1932: "I burnt down." (source shown on screen)

Built for the Meta Global AI Developer Hackathon (kicked off 26 October 2026, 17:00 Dutch time; runs to 4 November), track **Build for Your World**.

## Try it

The public judge page: **[JUDGE_URL_TO_FILL_IN_BY_OWNER]** (the owner adds the URL here on their go).

Watch the three example films first, then Try your own: take or choose a photo of an old, well-documented landmark, confirm the object, and watch the finished film. Tries are limited per visitor and per day (the page shows how many are left); past the limit, or when Try your own is resting, the page says so and points back to the examples. No access codes; nothing to install.

How each example was checked, scene by scene (bound quotes, sources, models, verdicts): on the judge page at `/examples/de-adriaan/evidence.html`, `/examples/major-oak/evidence.html` and `/examples/rubjerg-knude/evidence.html`.

## How it works

| Step | What happens | Model |
|---|---|---|
| 0. Identify | GPS, the location question, a typed place, or Muse Spark naming the landmark from the photo; nearby candidates come from Wikidata and Wikipedia (Overpass is off on the live path: it failed 61 of 62 stored jobs on 2-3 Nov and never decided an identification); the right one is picked from the photo and confirmed by you | Muse Spark (vision), [identify](witness/identify.py) |
| 1. Cut out | The object is segmented from today's photo, for the closing shot; command line with --subject only, as in the examples (uploads skip it) | SAM 3.1, [segment](witness/segment.py) |
| 2. Research | One grounded web question about the object's own life; every claim needs a URL | Muse Spark (web_search), [research](witness/research.py) |
| 3. Verify | Each claim is checked against the fetched source text; only fully supported claims reach the film, "partly" means no (a narrowed rewrite gets one check of its own as a new claim) | Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`), Meta fallback, [verify](witness/verify.py) |
| 4. Paint eras | Up to 4 decisive eras are painted with the object in its verified state, branching in parallel from one anchor so it stays recognisably the same place | Muse Image, [paint](witness/paint.py) |
| 5. Check the painting | Each painted era is looked at and compared with the object's verified state and final caption; a mismatch is repainted, at most twice | Muse Spark (vision), [check](witness/check.py) |
| 6. Film | Captions and citations are rendered to a 1080x1920 page, ending on your photo (MP4 export runs from the command line only) | (our renderer), [render](witness/render/builder.py) |

Every model called at runtime is a Meta model. Wikidata, Wikipedia and OpenStreetMap are data sources, not models.

Details: [docs/02_pipeline.md](docs/02_pipeline.md). The accuracy rules: [docs/03_accuracy.md](docs/03_accuracy.md).

## The picture-book version, in the examples

Uploads make the film only. Two of the three examples also carry a picture-book version: the same checked facts in simpler words, with picture-book paintings from the same anchor. De Adriaan is documentary-only: two of its picture-book paintings failed revalidation (see eval/example_revalidation_2026-11-04.json). The "spot the difference" game is built and appears only with 3 or more grounded changes; none of the three examples qualifies, so the submission ships no game. See [docs/08_picture_book.md](docs/08_picture_book.md).

## Principles

- **No source, no claim.** A caption without a verified source is not shown. Every accepted claim rests on a literal quote in a page we fetched, bound to that page's URL.
- **Nothing shown is ever withdrawn.** The film plays only when finished; scenes without evidence are refused by the renderer.
- **The object changes as its history says.** A windmill that burned is shown burnt; a tower that gained a wing shows it from that year. Its state in every era is a sourced claim, checked against the painting.
- **AI imagery is labelled** in every film, as Meta's Acceptable Use Policy and the EU AI Act expect.
- **No war, no politics.** Eras dominated by conflict or political events are left out (hackathon rule, and the films are about places, not battles).
- **Shipped examples pass today's checks.** The three example sets were revalidated on 3 Nov through the current caption and painting checks; every kept era carries a binding from those checks (see the evidence pages linked above).

## Run it yourself

### macOS

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/playwright install chromium   # only for recording MP4s
brew install ffmpeg                     # only for recording MP4s
```

### Linux

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/playwright install chromium   # only for recording MP4s
sudo apt install ffmpeg                 # only for recording MP4s
```

### Windows

Not tested. WSL2 with the Linux steps above should work, but is untested.

### Keys

```bash
cp .env.example .env.local   # add your keys; the CLI loads this file itself
```

`.env.example` holds names only:

- `MODEL_API_KEY` (required): the Meta Model API key. Without it every step refuses; nothing runs.
- `BASETEN_API_KEY` (optional): verification on the open-weights Muse Spark Open. Without it the checks fall back to Meta automatically (tested); films cost a little more and verify a little faster.
- `EUROPEANA_API_KEY` (not used yet): reserved for historical reference images, which are still in "Planned, not built".
- `META_API_KEY` (not used by the app): the author's coding-agent key, kept here so it is never committed.

### Make a film

```bash
.venv/bin/python -m witness film path/to/photo.jpg            # location from the photo's GPS data
.venv/bin/python -m witness film photo.jpg --place "Haarlem"  # when the photo has none
.venv/bin/python -m witness research photo.jpg --place "Haarlem"  # story only, no painting
```

One film end to end, straight to `out/<slug>/film/film.html`:

```bash
.venv/bin/python -m witness film photo.jpg --place "Haarlem"
```

The same run step by step (the slug is the folder name under
`out/`; `research` stops before painting):

```bash
.venv/bin/python -m witness research photo.jpg --place "Haarlem"
.venv/bin/python -m witness captions <slug>
.venv/bin/python -m witness paint <slug> --photo photo.jpg
.venv/bin/python -m witness render <slug> --photo photo.jpg
```

Location data identifies the object. On the web page it is held in the job's private hand-off file only until the worker reads it, then removed; the research keeps only a coarse season zone (north, south or tropical), and the film, the logs and the job store never carry the location at all.

### Example films

The three example films are on the judge page and in the video. They're not in this repository, to keep it small (67 MB of images). All three source photos carry a recorded licence in their `film.json` (CC0, CC BY 3.0 and CC BY 4.0, with author and file link).

## Cost and speed

Measured 30 Oct from the saved token counts (research) plus the shipped paintings ($0.01 each):

- De Adriaan: $0.55 research + 6 paintings = about $0.62.
- Major Oak: $0.23 research + 4 paintings = about $0.28.
- Rubjerg Knude: $0.28 research + 6 paintings = about $0.35.

Every billable call reserves an estimate-based ceiling before it runs (`max_tool_calls` bounds the searches, not the input tokens the searches return, so one call can overshoot). The daily cap, the Meta credit balance and a Modal workspace budget are the outer controls; the owner sets the budget.

Caption and check text tokens and web-search counts are tallied in process but not saved, so they are missing from these totals. The support vote was evaluated on two developer-written sets from the 3 demo films, mostly from Wikipedia (run 30 Oct to 1 Nov, before the low-effort switch): 53 cases (open 52 valid correct; Meta 47 valid with 5 errors failing closed; 1 shared false rejection) plus 28 harder cases with prompt injections (open 28; Meta 25 valid with 3 errors failing closed). Both arms agree on every accept or not-accept decision, so the sets are regression evidence on these cases but do not separate the models; at that time the open model matched Meta at lower cost and higher latency. On 3 Nov the same 81 cases were re-run on Baseten with `reasoning_effort` omitted against `low`: both arms right on all 81, no flips, about 4x fewer completion tokens on `low` (raw outputs: [support](eval/support_low_results_2026-11-03.json), [hard](eval/hard_low_results_2026-11-03.json)). The eval tests isolated support votes only, not anchors, captions, state, painting or rendering. See [docs/04_demo.md](docs/04_demo.md) and [docs/07_test_set.md](docs/07_test_set.md).

Measured 2 Nov on staging (De Adriaan, one full Try-your-own, paid): Identify 33 s, Research 49 s, Check 91 s, Paint 272 s (captions 47 s, painting 225 s), Film 3 s; 454 s wall to the film (about 8 minutes). Model-API ledger delta $1.03 (56 paid calls; film job ledger $0.52, extras started). Modal compute about $0.005 for the film ($0.01 metered for the whole staging session, $0.00 billed after credits).

## Planned, not built

Period-figure layers, live streaming playback, captions in languages other than English, automatic reference images from Commons or Europeana, films of 5 to 7 scenes, "add a source" and "tell what you know" fallbacks, an MP4 download button on the web page, voice narration, accounts and payments. Spot the difference as flip cards: each card asks what changed between a painted era and today's photo. Tap it to flip it and see the answer with its source. It's shown only when at least three checked changes exist.

## Prior work

Nothing existed before; it was built from scratch during the hackathon, from 26 Oct 2026 (see the history). Cited third-party words (source quotes, package pins) excepted, everything in this repository was written in that window. The git history is the record, day by day in [docs/05_build_log.md](docs/05_build_log.md).

## Licence

MIT. See [LICENSE](LICENSE).
