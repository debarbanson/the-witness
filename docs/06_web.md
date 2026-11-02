# 06 The web page

The judges score "does the product hold up live", so the pipeline gets a small mobile web page. No app store: a link that works on any phone.

## The flow

1. **Open the link** on a phone. One screen: "Point me at something old."
2. **Take or pick a photo.** A file picker for an image file; on phones the OS usually offers the camera among the sources.
3. **Location.** If the photo carries GPS data, use it. If not, ask the browser (`navigator.geolocation`, with a one-line reason). If refused, a text field: "Where is it?"
4. **Confirm the object.** Step 0 shows its best match: "Is this De Adriaan, Haarlem?" with the name and kind. Yes, or cancel. Only identification runs before you confirm; research and painting wait for yes.
5. **Watch it being made.** Honest progress with a timer while the film builds: a live clock with phase words that change as each step lands (a long painting or vote can run quiet between them). A closed tab cancels the job.
6. **The film.** A link to the film page once finished: it plays in the browser, vertical, with clickable sources below, pause and replay, and an Adults/Children switch. Facts-only results show the verified facts with their source links instead. ("Download" and "Share" making the MP4 on the page are planned after the deploy.)
7. **When there is too little** (pipeline step 3b): a short film, an honest facts-only card, or a partial result that says what is missing. ("Add a source" and "Tell what you know" are planned.)

## How it is built

- **Back end:** Python, a small FastAPI app around the same `witness` package the command line uses. A film takes minutes, so `POST /api/jobs` starts a job and returns its id; `GET /api/jobs/{id}` returns its progress events and, at the end, the film and sources.
- **Front end:** one static HTML page with plain JavaScript, no framework. It polls the job, renders the progress events with a timer, and plays the finished film with the same renderer code the MP4 export uses.
- **Rendering on the server:** the page plays the film in the browser. MP4 export runs from the command line only and needs Playwright with Chromium and ffmpeg; a download button on the page is planned.
- **Cache:** on the command line, reviewed research is kept by Wikidata id plus language, and a fresh film is reused from its folder for a week, so a known object opens at once. The web page has no shared cache: every upload researches fresh (the reviewed example films are served as static pages). Only research results and paintings are cached, never the visitor's photo or location.
- **Modal uploads:** the image is built from an allowlist (the witness package plus the reviewed example films; out/cache, samples and .env.local never go in, and Modal has no ignore file). The web job starts with an empty cache or one seeded only from the reviewed demo objects. Example films bake in only when their folders exist locally; missing ones are skipped with a log line, so a fresh clone still deploys. The films stay git-ignored until the owner decides.
- **Hosting: Modal.** A Modal account exists (workspace `debarbanson`), and the hackathon's $100 Modal credits were requested on 26 Oct (selected teams only, not guaranteed). Deploy blocked on owner credentials (30 Oct): Modal authenticates through its own CLI (`modal token new`, stored outside the repo), and the app's keys go into Modal secrets, never into the repo. Fallback: another container host. It must stay up through judging (5 to 9 November).
- **Limits for a public link:** reviewed example films for everyone, plus a limited "Try your own". One budget authority admits each film (per-visitor limit, daily quota) and reserves a ceiling before every billable call, reconciling after; it fails closed when accounting is unavailable. Meta's "Spend Limit" is only an alert and does not stop billing (hackathon FAQ, 26 Oct), so the app itself refuses new films past the quota; past the $150 credits, usage is charged to the card.

## Privacy

- No accounts, no analytics. One `vid` session cookie so a visitor sees only their own jobs, plus a keyed daily hash of the network address for the quota (the raw address is never stored). The server-side records are deleted by a daily sweep once the job ended more than 24 h ago, so between one and two days after it ends.
- The photo is normalised at upload (orientation applied, metadata stripped) and kept until that sweep, then deleted. Coordinates wait in the job's private folder (spec.json, read only by the worker) and are deleted with it; lookups run in memory and error text carries no query strings.
- The page says this in one line under the upload button.

## Out of scope

Sharing links, galleries, user history, payments.
