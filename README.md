# The Witness

One photo of something old. A one-minute film of everything it has seen.

Point The Witness at a windmill, an old tree or a lighthouse. It researches the object's history on the web, then paints each era it lived through: the world around it, and the object itself as it was then, built, damaged, rebuilt, as the sources say. Your own photo closes the film as "today". The result is a 40 to 60 second vertical film, told in the first person by the object, where every caption carries its source.

> "I was built in 1781 to drain the polder." (source shown on screen)

Built for the Meta Global AI Developer Hackathon (27 October to 4 November 2026), track **Build for Your World**.

## How it works

| Step | What happens | Meta model |
|---|---|---|
| 0. Identify | The photo's location finds nearby known objects (OpenStreetMap); the right one is picked from the photo and confirmed by you | Muse Spark (vision) |
| 1. Cut out | The object is segmented from today's photo, for the closing shot | SAM 3.1 |
| 2. Research | One grounded web question per era, including what the object itself looked like then; every claim needs a URL | Muse Spark (web_search) |
| 3. Verify | A second pass checks each claim against the source text; unsupported claims are dropped | Muse Spark |
| 4. Paint eras | Each era is painted with the object in its verified state, branching in parallel from one anchor so it stays recognisably the same place | Muse Image |
| 5. Check the painting | Each painted era is looked at and compared with the object's verified state; a mismatch is repainted | Muse Spark (vision) |
| 6. Layers | People in each painted era are segmented into layers that move with the painting | SAM 3.1 |
| 7. Film | Layers, captions and citations are rendered to a 1080x1920 video, ending on your photo | (our renderer) |

Details: [docs/02_pipeline.md](docs/02_pipeline.md). The accuracy rules: [docs/03_accuracy.md](docs/03_accuracy.md).

## For adults and for children

Every film has a children's version (8+): the same verified facts in simpler words, picture-book paintings, and a "spot the difference" game between a painted era and your photo of today. See [docs/08_children.md](docs/08_children.md).

## Principles

- **No source, no claim.** A caption without a verified source is not shown.
- **The object changes as its history says.** A windmill that burned is shown burnt; a tower that gained a wing shows it from that year. Its state in every era is a sourced claim, checked against the painting.
- **AI imagery is labelled** in every film, as Meta's Acceptable Use Policy and the EU AI Act expect.
- **No war, no politics.** Eras dominated by conflict or political events are left out (hackathon rule, and the films are about places, not battles).

## Use it

- **On your phone:** open the web page, take a photo, allow location (or type the place), confirm the object, watch the film being made. See [docs/06_web.md](docs/06_web.md).
- **From the command line:**

```bash
cp .env.example .env.local   # add your Model API key
python -m witness film path/to/photo.jpg            # location from the photo's GPS data
python -m witness film photo.jpg --place "Haarlem"  # when the photo has none
```

(These are the target interfaces; see the build log for what exists today.)

Location data is used only to identify the object and is never stored or written into the film.

## Built during the hackathon

Everything in this repository was written between the kickoff on 26 October and 4 November 2026. The day-by-day record is in [docs/05_build_log.md](docs/05_build_log.md).

## Licence

MIT for the code. Generated images carry Meta's provenance signals and the on-screen AI label; reference images are public domain, CC0 or CC BY, listed and credited per film.
