# 06 The web page

The judges score "does the product hold up live", so the pipeline gets a small mobile web page. No app store: a link that works on any phone.

## The flow

1. **Open the link** on a phone. One screen: "Point me at something old."
2. **Take or pick a photo.** A file picker for an image file; on phones the OS usually offers the camera among the sources.
3. **Location.** If the photo carries GPS data, use it. If not, ask the browser (`navigator.geolocation`, with a one-line reason). If refused, a text field: "Where is it?"
4. **Confirm the object.** Step 0 shows its best match, named with its Wikidata description ("Is this Poldertoren, water tower in Noordoostpolder?"). Yes, or cancel. Only identification runs before you confirm; research and painting wait for yes.
5. **Watch it being made.** Honest progress with a timer while the film builds: a live clock with phase words that change as each step lands (a long painting or vote can run quiet between them). Only the Cancel button cancels the job; closing the tab, locking the phone or switching apps lets the film keep going, and coming back in the same browser shows it again. A "Show the model calls" toggle under the step list shows each model call as it lands.
6. **The film.** A link to the film page once finished: it plays in the browser, vertical, with clickable sources below, pause and replay, and a Documentary/Picture-book switch on the examples. Facts-only results show the verified facts with their source links instead. ("Download" and "Share" making the MP4 on the page are planned after the deploy.)
7. **When there is too little** (pipeline step 3b): a short film, an honest facts-only card, or a partial result that says what is missing. ("Add a source" and "Tell what you know" are planned.)

## How it is built

- **Back end:** Python, a small FastAPI app around the same `witness` package the command line uses. A film takes minutes, so `POST /api/jobs` starts a job and returns its id; `GET /api/jobs/{id}` returns its progress events and, at the end, the film and sources.
- **Front end:** one static HTML page with plain JavaScript, no framework. It polls the job, renders the progress events with a timer, and plays the finished film with the same renderer code the MP4 export uses.
- **Rendering on the server:** the page plays the film in the browser. MP4 export runs from the command line only and needs Playwright with Chromium and ffmpeg; a download button on the page is planned.
- **Cache:** on the command line, reviewed research is kept by Wikidata id plus language, and a fresh film is reused from its folder for a week, so a known object opens at once. The web page has no shared cache: every upload researches fresh (the reviewed example films are served as static pages). Only research results and paintings are cached, never the visitor's photo or location.
- **Modal uploads:** the image holds only the witness package (out/cache, samples and .env.local never go in, and Modal has no ignore file). The web job starts with an empty cache or one seeded only from the reviewed demo objects. The reviewed example films are uploaded once to a shared Volume and read when each app instance starts; missing ones are skipped with a log line, so a fresh clone still deploys. Upload before deploying, or redeploy/restart after uploading. The films stay git-ignored until the owner decides.
- **Hosting: Modal.** A Modal account exists (workspace `debarbanson`), and the hackathon's $100 Modal credits were requested on 26 Oct (selected teams only, not guaranteed). Deploys run from a machine with Modal access: Modal authenticates through its own CLI (`modal token new`, stored outside the repo), and the app's keys go into Modal secrets, never into the repo. The `the-witness-keys` secret must hold `WITNESS_CONTACT` (the notice address) and `WITNESS_IP_SECRET` (one random value shared by every container for the visitor hash). Fallback: another container host. The demo must stay up through the community vote (until 16 November) if it stays public.
- **Limits for a public link:** reviewed example films for everyone, plus a limited "Try your own". One budget authority admits each film (per-browser, per-network and daily quotas; a spawn that never starts refunds its admission) and reserves a ceiling before every billable call, reconciling after; it fails closed when accounting is unavailable. Meta's "Spend Limit" is only an alert and does not stop billing (hackathon FAQ, 26 Oct), so the app itself refuses new films past the quota; past the $150 credits, usage is charged to the card. The hard dollar cap stays the real spending guard; the film counts only keep one visitor from using a day's budget.

## Privacy

- No accounts, no analytics. One `vid` session cookie so a visitor sees only their own jobs, plus a keyed daily hash of the network address for the quota (the raw address is never stored). The server-side records are deleted by an hourly sweep once the job ended over 24 h ago, so within the hour after the deadline. Visitor hashes in the ledger expire 24 h after they are written. Per-day ledger totals are kept while the day's record lives (today and yesterday); older daily records are dropped whole.
- The photo is normalised at upload (orientation applied, metadata stripped) and kept until that sweep, then deleted. Coordinates and the typed place are held in the job's private hand-off file (spec.json) only until the worker reads it, then removed; lookups run in memory and error text carries no query strings.
- Job records live in a Modal Dict that survives deploys (https://modal.com/docs/guide/dicts); entries expire after 7 days with no reads or writes. The 2 Nov observation of only 3 records is unexplained; the hourly sweep removes orphan folders either way. Live check 3 Nov 11:50: 60 records for 61 folders, oldest 13.9 h, across nine deploys.
- The page says this in one line under the upload button.

## Deploy runbook

One deploy carries both surfaces: the staging page (`web`, behind proxy auth) and judge mode (`judge`, public and unlisted, no proxy auth, noindex on every response). The deploy prints both URLs; the judge URL goes in the README (owner fills it in on their go).

### Before the first deploy

1. The owner runs `modal token new` on their own machine (Modal credentials live outside the repo).
2. The owner creates the secret `the-witness-keys` in the Modal dashboard, never from the command line, with these names (no values anywhere in the repo or the shell history):
   - `MODEL_API_KEY` (Meta calls: research, verify, paint, picture-book),
   - `BASETEN_API_KEY` (open-weights support votes),
   - `WITNESS_CONTACT` (the notice address),
   - `WITNESS_IP_SECRET` (at least 32 characters of randomness, shared by every container for the visitor hash),
   - `WITNESS_JUDGE_CAP_USD` (judge mode's hard daily spending cap; the owner sets the number after the staging measurement),
   - optionally `WITNESS_DAILY_FILMS`, `WITNESS_VISITOR_FILMS` and `WITNESS_NETWORK_FILMS` (film limits; defaults 10 total, 2 per browser, 2 per network; a present but blank, zero, negative or non-integer value refuses startup).
3. Staging test flags live in the same secret only for abuse runs: `WITNESS_ABUSE_RESET=1` (lets the staging abuse script reset quotas between cases; never set on judge mode) and `WITNESS_FAKE_PROVIDER=1` with `WITNESS_FAKE_DELAY_S=2` (cancel-path cases without paid calls).

### Staging

```bash
modal deploy modal_app.py
```

This deploys staging (`web`) and judge mode together; test on the staging URL first. Upload each reviewed example film to the shared Volume before deploying (the app reads the example list once at startup and skips missing ones with a log line); if you upload later, redeploy afterwards:

```bash
modal volume put witness-examples out/q2763574-de-adriaan/film de-adriaan
modal volume put witness-examples out/q388443-major-oak/film major-oak
modal volume put witness-examples out/q2206180-rubjerg-knude-fyr/film rubjerg-knude
modal volume ls witness-examples
```

One `put` per reviewed example: the finished `film/` folder (film pages, paintings, `evidence.html`) under its public slug.

### Redeploys: drain first

Before redeploying or stopping the app, let running films finish: a deploy while a film runs can strand it mid-job. Never run two deploys at once, and never leave an old deployment running next to a new one: two ledger writers at once can admit past the cap. Check that no upload is in progress (nothing but finished films in the last minutes), then deploy once.

### Production (judge mode)

Judge mode deploys with the same command; there is no separate build. Before sharing its URL: the examples are uploaded, `WITNESS_JUDGE_CAP_USD` is set, neither `WITNESS_ABUSE_RESET` nor `WITNESS_FAKE_PROVIDER` is set, and the smoke checks below pass on the judge URL. Tag `v1.0-submission` only on the owner's go, after those checks.

### Smoke checks

Run these on staging first, then on the judge URL. Staging sits behind proxy auth: create a Token ID/Secret pair in the dashboard (Settings, proxy-auth tokens) and pass it on staging requests:

```bash
export MODAL_PROXY_KEY=<token-id> MODAL_PROXY_SECRET=<token-secret>
auth=(-H "Modal-Key: $MODAL_PROXY_KEY" -H "Modal-Secret: $MODAL_PROXY_SECRET")
```

The judge URL needs no auth headers.

1. The page: `curl "${auth[@]}" -s -o /dev/null -w "%{http_code}\n" <url>/` answers 200.
2. One example film: `curl "${auth[@]}" -s -o /dev/null -w "%{http_code}\n" <url>/examples/<slug>/` answers 200, and its page assets load.
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

Measured 2 Nov on staging (De Adriaan, one full Try-your-own, paid): Identify 33 s, Research 49 s, Check 91 s, Paint 272 s (captions 47 s, painting 225 s), Film 3 s; 454 s wall to the film (about 8 minutes). Model-API ledger delta $1.03 (56 paid calls; film job ledger $0.52, extras started). Modal compute about $0.005 for the film (`modal billing report --for today`; $0.01 metered for the whole staging session, $0.00 billed after credits).

The owner-side run, on a machine with Modal access, in this order: cap first, examples before deploy, abuse run, flags out, drain, redeploy, then smoke checks.

```bash
# 1. set a valid WITNESS_JUDGE_CAP_USD in the-witness-keys first:
#    judge mode cannot start without it, and every capless start
#    alerts the owner
# 2. upload the reviewed examples (the three puts above)
modal deploy modal_app.py
export MODAL_PROXY_KEY=<token-id> MODAL_PROXY_SECRET=<token-secret>
.venv/bin/python scripts/abuse_staging.py <staging-url>
```

1. One full Try-your-own film on staging, on a well-documented object: submit through the staging page, record the wall time per phase from the progress events and the total cost from the ledger (`GET /api/debug/ledger`, `total_usd` delta).
2. The abuse script above (16 checks, each asserting on effects; it refuses unless `WITNESS_ABUSE_RESET=1` is in the staging secret).
3. After the abuse run, remove the three test flags from the secret (`WITNESS_ABUSE_RESET`, `WITNESS_FAKE_PROVIDER`, `WITNESS_FAKE_DELAY_S`), drain (no film in progress), redeploy, and confirm staging runs in real mode and judge mode starts: the judge URL answers 200 and serves an example film. Judge mode refuses to start while either of the first two flags is set, and its worker refuses fake films.
4. Put the dated numbers in the README and here, and set `WITNESS_JUDGE_CAP_USD` so 5 to 16 Nov (judging plus the community vote) fits the remaining credits.

### Freeze

The repo is frozen at the deadline: Wed 4 Nov 21:00 ET (Thu 5 Nov 03:00 in the Netherlands). Aim to finish code and README by Wednesday 18:00 Dutch time. After the deadline the judge app runs the submitted commit unchanged: only the off switch and the limit values in the secret or Dict may change; no new code and no redeploys of new code. The `v1.0-submission` tag waits for the owner's go.

### Known limits

A failed spawn refunds the visitor quota even when the worker may have started (the spawn reply was lost but the worker runs), and refunds carry no ticket id, so a lost reply can free a quota another film then spends. No public route triggers this on purpose; the window is one lost spawn reply. A ticketed fix did not fit before the freeze.

## Out of scope

Sharing links, galleries, user history, payments.
