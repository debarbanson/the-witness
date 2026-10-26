# The Witness

One photo of something old. A one-minute film of everything it has seen.

Point The Witness at a windmill, an old tree or a lighthouse. It cuts the object out of your photo, researches its history on the web, and paints each era it lived through around it, with the object itself kept exactly as you photographed it. The result is a 40 to 60 second vertical film, told in the first person by the object, where every caption carries its source.

> "I was built in 1781 to drain the polder." (source shown on screen)

Built for the Meta Global AI Developer Hackathon (27 October to 4 November 2026), track **Build for Your World**.

## How it works

| Step | What happens | Meta model |
|---|---|---|
| 1. Cut out | The object is segmented from the photo, pixel-exact | SAM 3.1 |
| 2. Research | One grounded web question per era; every claim needs a URL | Muse Spark (web_search) |
| 3. Verify | A second pass checks each claim against the source text; unsupported claims are dropped | Muse Spark / Muse Wonder |
| 4. Paint eras | Each era is painted around the object, chained to one anchor so the series stays consistent | Muse Image |
| 5. Layers | People in each painted era are segmented into their own layer for depth | SAM 3.1 |
| 6. Film | Layers, captions and citations are rendered to a 1080x1920 video | (our renderer) |

Details: [docs/02_pipeline.md](docs/02_pipeline.md). The accuracy rules: [docs/03_accuracy.md](docs/03_accuracy.md).

## Principles

- **No source, no claim.** A caption without a verified source is not shown.
- **The object is never generated.** It is your photo, cut out; only the world around it is painted.
- **AI imagery is labelled** in every film, as Meta's Acceptable Use Policy and the EU AI Act expect.
- **No war, no politics.** Eras dominated by conflict or political events are left out (hackathon rule, and the films are about places, not battles).

## Run it

```bash
cp .env.example .env.local   # add your Model API key
python -m witness film path/to/photo.jpg --subject "windmill" --place "Kinderdijk, Netherlands"
```

(Commands are the target interface; see the build log for what exists today.)

## Built during the hackathon

Everything in this repository was written between 27 October and 4 November 2026. The day-by-day record is in [docs/05_build_log.md](docs/05_build_log.md).

## Licence

MIT for the code. Generated images carry Meta's provenance signals and the on-screen AI label; reference images are public domain only, listed per film.
