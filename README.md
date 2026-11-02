# The Witness

One photo of something old. A short film of the decisive eras it lived through.

Point The Witness at a windmill, an old tree or a lighthouse. It works out which object the photo shows, researches its history on the web, checks every claim against the fetched sources, then paints the decisive eras it lived through: the world around it, and the object itself as it was then, built, damaged, rebuilt, as the sources say. Changes are shown only where an accepted, sourced claim supports them; that is what the sources support, not a guarantee of historical truth. Your own photo closes the film as "today". The result is a vertical film of about 30 to 37 seconds, told in the first person by the object, where every caption carries its source.

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

Films that earn them get a children's version (8+) and a game: the same verified facts in simpler words, rechecked against the same sources, with picture-book paintings from the same anchor and a "spot the difference" game between a painted era and your photo of today. Both need enough verified material, so some films ship without one or both. See [docs/08_children.md](docs/08_children.md).

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
- **From the command line:** (commands use the project venv)

```
cp .env.example .env.local   # add your keys; the CLI loads this file itself
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

## Cost and speed

Measured 30 Oct from the saved token counts (research) plus the shipped paintings ($0.01 each):

- De Adriaan: $0.55 research + 6 paintings = about $0.62.
- Major Oak: $0.23 research + 4 paintings = about $0.28.
- Rubjerg Knude: $0.28 research + 6 paintings = about $0.35.

Caption and check text tokens and web-search counts are tallied in process but not saved, so they are missing from these totals. The support vote was evaluated on two developer-written sets from the 3 demo films, mostly from Wikipedia: 53 cases (open 52 valid correct; Meta 47 valid with 5 errors failing closed; 1 shared false rejection) plus 28 harder cases with prompt injections (open 28; Meta 25 valid with 3 errors failing closed). Both arms agree on every accept or not-accept decision, so the sets are regression evidence on these cases but do not separate the models; the open model matches Meta at lower cost and higher latency. The eval tests isolated support votes only, not anchors, captions, state, painting or rendering. See [docs/04_demo.md](docs/04_demo.md) and [docs/07_test_set.md](docs/07_test_set.md).

Measured 2 Nov on staging (De Adriaan, one full Try-your-own, paid): Identify 33 s, Research 49 s, Check 91 s, Paint 272 s (captions 47 s, painting 225 s), Film 3 s; 454 s wall to the adult film (about 8 minutes). Model-API ledger delta $1.03 (56 paid calls; adult job ledger $0.52, extras started). Modal compute about $0.005 for the film ($0.01 metered for the whole staging session, $0.00 billed after credits).

## Planned, not built

Period-figure layers, live streaming playback, captions in languages other than English, automatic reference images from Commons or Europeana, films of 5 to 7 scenes, "add a source" and "tell what you know" fallbacks, an MP4 download button on the web page, voice narration, accounts and payments.

## Built during the hackathon

Built during the hackathon, beginning 26 October 2026. Cited third-party words (source quotes, package pins) excepted, everything in this repository was written in that window. The git history is the record, day by day in [docs/05_build_log.md](docs/05_build_log.md).

## Licence

MIT. See [LICENSE](LICENSE).
