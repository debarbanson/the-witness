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
- **Modal uploads:** the image holds only the witness package (out/cache, samples and .env.local never go in, and Modal has no ignore file). The web job starts with an empty cache or one seeded only from the reviewed demo objects. The reviewed example films are uploaded once to a shared Volume and discovered at request time; missing ones are skipped with a log line, so a fresh clone still deploys. The films stay git-ignored until the owner decides.
- **Hosting: Modal.** A Modal account exists (workspace `debarbanson`), and the hackathon's $100 Modal credits were requested on 26 Oct (selected teams only, not guaranteed). Deploy blocked on owner credentials (30 Oct): Modal authenticates through its own CLI (`modal token new`, stored outside the repo), and the app's keys go into Modal secrets, never into the repo. The `the-witness-keys` secret must hold `WITNESS_CONTACT` (the notice address) and `WITNESS_IP_SECRET` (one random value shared by every container for the visitor hash). Fallback: another container host. It must stay up through judging (5 to 9 November).
- **Limits for a public link:** reviewed example films for everyone, plus a limited "Try your own". One budget authority admits each film (per-visitor limit, daily quota) and reserves a ceiling before every billable call, reconciling after; it fails closed when accounting is unavailable. Meta's "Spend Limit" is only an alert and does not stop billing (hackathon FAQ, 26 Oct), so the app itself refuses new films past the quota; past the $150 credits, usage is charged to the card.

## Privacy

- No accounts, no analytics. One `vid` session cookie so a visitor sees only their own jobs, plus a keyed daily hash of the network address for the quota (the raw address is never stored). The server-side records are deleted by an hourly sweep once the job ended over 24 h ago, so within the hour after the deadline. Visitor hashes in the ledger expire 24 h after they are written. Per-day ledger totals are kept while the day's record lives (today and yesterday); older daily records are dropped whole.
- The photo is normalised at upload (orientation applied, metadata stripped) and kept until that sweep, then deleted. Coordinates and the typed place are held in the job's private hand-off file (spec.json) only until the worker reads it, then removed; lookups run in memory and error text carries no query strings.
- The page says this in one line under the upload button.

## Deploy runbook

One deploy carries both surfaces: the staging page (`web`, behind proxy auth) and judge mode (`judge`, public and unlisted, no proxy auth, noindex on every response). The deploy prints both URLs; share the judge URL only in the submission.

### Before the first deploy

1. The owner runs `modal token new` on their own machine (Modal credentials live outside the repo).
2. The owner creates the secret `the-witness-keys` in the Modal dashboard, never from the command line, with these names (no values anywhere in the repo or the shell history):
   - `MODEL_API_KEY` (Meta calls: research, verify, paint, children),
   - `BASETEN_API_KEY` (open-weights support votes),
   - `WITNESS_CONTACT` (the notice address),
   - `WITNESS_IP_SECRET` (at least 32 characters of randomness, shared by every container for the visitor hash),
   - `WITNESS_JUDGE_CAP_USD` (judge mode's hard daily spending cap; the owner sets the number after the staging measurement).
3. Staging test flags live in the same secret only for abuse runs: `WITNESS_ABUSE_RESET=1` (lets the staging abuse script reset quotas between cases; never set on judge mode) and `WITNESS_FAKE_PROVIDER=1` with `WITNESS_FAKE_DELAY_S=2` (cancel-path cases without paid calls).

### Staging

```bash
modal deploy modal_app.py
```

This deploys staging (`web`) and judge mode together; test on the staging URL first. Upload each reviewed example film to the shared Volume (the app discovers them at request time and skips missing ones with a log line):

```bash
modal volume put witness-examples out/de-adriaan/film de-adriaan
modal volume ls witness-examples
```

One `put` per reviewed example, one slug per film directory.

### Production (judge mode)

Judge mode deploys with the same command; there is no separate build. Before sharing its URL: the examples are uploaded, `WITNESS_JUDGE_CAP_USD` is set, `WITNESS_ABUSE_RESET` is not set on the judge path, and the smoke checks below pass on the judge URL. Tag `v1.0-submission` only on the owner's go, after those checks.

### Smoke checks

Run these on staging first, then on the judge URL:

1. The page: `curl -s -o /dev/null -w "%{http_code}\n" <url>/` answers 200.
2. One example film: `curl -s -o /dev/null -w "%{http_code}\n" <url>/examples/<slug>/` answers 200, and its page assets load.
3. Security headers: the response carries `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options` and `Referrer-Policy`. On judge mode it also carries `X-Robots-Tag: noindex`, and `<url>/robots.txt` disallows everything.
4. The off switch: `modal run modal_app.py::try_switch --no-enable` turns Try your own off within a minute; `POST /api/jobs` then answers 503 with the resting line while the examples keep serving. `modal run modal_app.py::try_switch --enable` turns it back on.
5. One capped request: submit one Try-your-own photo on staging and watch it finish inside the staging cap, or be refused with a quota error when the cap is spent.

### Turning Try your own off and on

```bash
modal run modal_app.py::try_switch --no-enable   # off within a minute, no redeploy
modal run modal_app.py::try_switch --enable      # back on
```

Off means: new `POST /api/jobs` on judge mode answers 503 ("Try your own is resting; the examples are below"). In-flight jobs finish; the examples and everything else keep working. Staging has no off switch: proxy auth keeps it private.

### Costs and caps

The staging measurement (one full Try-your-own run plus the abuse script) sets the numbers; until then the README and this page carry no cost claims. The judge cap must cover judging (5 to 8 Nov) and the community vote (until 16 Nov) within the remaining credits; the proposal goes in the Block N report.

## Out of scope

Sharing links, galleries, user history, payments.
