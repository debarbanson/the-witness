# The Witness

One photo of something old. A short film of the decisive eras it lived through.

Point The Witness at a windmill, an old tree or a lighthouse. It works out which object the photo shows, researches its history on the web, checks every claim against the fetched sources, then paints the decisive eras it lived through: the world around it, and the object itself as it was then, built, damaged, rebuilt, as the sources say. Your own photo closes the film as "today". The result is a vertical film of about 30 to 37 seconds, told in the first person by the object, where every caption carries its source.

> "I burnt down on 23 April 1932." (source shown on screen)

Built for the Meta Global AI Developer Hackathon (kicked off 26 October 2026, 17:00 Dutch time; runs to 4 November), track **Build for Your World**.

## How it works

| Step | What happens | Model |
|---|---|---|
| 0. Identify | The photo's location finds nearby known objects (OpenStreetMap, Wikidata); the right one is picked from the photo and confirmed by you | Muse Spark (vision) |
| 1. Cut out | The object is segmented from today's photo, for the closing shot | SAM 3.1 |
| 2. Research | One grounded web question about the object's own life; every claim needs a URL | Muse Spark (web_search) |
| 3. Verify | Each claim is checked against the fetched source text; only fully supported claims reach the film, "partly" means no | Muse Spark Open on Baseten, Meta fallback |
| 4. Paint eras | Up to 4 decisive eras are painted with the object in its verified state, branching in parallel from one anchor so it stays recognisably the same place | Muse Image |
| 5. Check the painting | Each painted era is looked at and compared with the object's verified state and final caption; a mismatch is repainted, at most twice | Muse Spark (vision) |
| 6. Film | Captions and citations are rendered to a 1080x1920 page, ending on your photo (MP4 export runs from the command line only) | (our renderer) |

Details: [docs/02_pipeline.md](docs/02_pipeline.md). The accuracy rules: [docs/03_accuracy.md](docs/03_accuracy.md).

## For adults and for children

Every film has a children's version (8+): the same verified facts in simpler words, rechecked against the same sources, with picture-book paintings from the same anchor and a "spot the difference" game between a painted era and your photo of today. See [docs/08_children.md](docs/08_children.md).

## Principles

- **No source, no claim.** A caption without a verified source is not shown. Every accepted claim rests on a literal quote in a page we fetched, bound to that page's URL.
- **Nothing shown is ever withdrawn.** The film plays only when finished; scenes without evidence are refused by the renderer.
- **The object changes as its history says.** A windmill that burned is shown burnt; a tower that gained a wing shows it from that year. Its state in every era is a sourced claim, checked against the painting.
- **AI imagery is labelled** in every film, as Meta's Acceptable Use Policy and the EU AI Act expect.
- **No war, no politics.** Eras dominated by conflict or political events are left out (hackathon rule, and the films are about places, not battles).

## Use it

Set up (Python 3.12; `requirements-lock.txt` pins every dependency):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/playwright install chromium   # only for recording MP4s
brew install ffmpeg                     # only for recording MP4s (apt on Linux)
```

- **On your phone (after the deploy; the link stays private until the abuse tests pass):** open the web page, take or pick a photo, allow location (or type the place), confirm the object, watch the finished film. See [docs/06_web.md](docs/06_web.md).
- **From the command line:**

```bash
cp .env.example .env.local   # add your keys; the CLI loads this file itself
python -m witness film path/to/photo.jpg            # location from the photo's GPS data
python -m witness film photo.jpg --place "Haarlem"  # when the photo has none
python -m witness research photo.jpg --place "Haarlem"  # story only, no painting
```

Location data is used only to identify the object and is never stored or written into the film.

## Cost and speed

Measured 30 Oct from the saved token counts (research) plus the shipped paintings ($0.01 each):

- De Adriaan: $0.55 research + 6 paintings = about $0.62.
- Major Oak: $0.23 research + 4 paintings = about $0.28.
- Rubjerg Knude: $0.28 research + 6 paintings = about $0.35.

Caption and check text tokens and web-search counts are tallied in process but not saved, so they are missing from these totals. The support vote was evaluated on two developer-written sets from the 3 demo films, mostly from Wikipedia: 53 cases (52 of 53 on each arm) plus 28 harder cases with prompt injections (28 of 28 on each arm). Both arms agree on every case, so the sets bound the risk but do not separate the models; the open model matches Meta at lower cost and higher latency. End-to-end upload-to-film time will be measured on staging after the deploy; see [docs/04_demo.md](docs/04_demo.md) and [docs/07_test_set.md](docs/07_test_set.md).

## Planned, not built

Period-figure layers, live streaming playback, captions in languages other than English, automatic reference images from Commons or Europeana, films of 5 to 7 scenes, "add a source" and "tell what you know" fallbacks, an MP4 download button on the web page, voice narration, accounts and payments.

## Built during the hackathon

Everything in this repository was written between the kickoff on 26 October and 4 November 2026. The day-by-day record is in [docs/05_build_log.md](docs/05_build_log.md).

## Licence

The licence choice waits for the owner's decision.
