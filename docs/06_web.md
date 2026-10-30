# 06 The web page

The judges score "does the product hold up live", so the pipeline gets a small mobile web page. No app store: a link that works on any phone.

## The flow

1. **Open the link** on a phone. One screen: "Point me at something old."
2. **Take or pick a photo.** `<input type="file" accept="image/*" capture="environment">` opens the camera on phones.
3. **Location.** If the photo carries GPS data, use it. If not, ask the browser (`navigator.geolocation`, with a one-line reason). If refused, a text field: "Where is it?"
4. **Confirm the object.** Step 0 shows its best match: "Is this De Adriaan, Haarlem?" with the name and kind. Yes, or cancel. No paid work runs before you confirm.
5. **Watch it being made.** Honest progress with a timer while the film builds: what is happening now, never more than 10 to 15 s without an update. A closed tab cancels the job.
6. **The film.** It plays inline once finished: the page renders it live in the browser, vertical, with clickable sources below, pause and replay, and an Adults/Children switch. "Download" or "Share" makes the MP4 in the background.
7. **When there is too little** (pipeline step 3b): a short film, an honest facts-only card, or a partial result that says what is missing. ("Add a source" and "Tell what you know" are planned.)

## How it is built

- **Back end:** Python, a small FastAPI app around the same `witness` package the command line uses. A film takes minutes, so `POST /films` starts a job and returns its id; `GET /films/{id}` returns its progress events and, at the end, the film and sources.
- **Front end:** one static HTML page with plain JavaScript, no framework. It polls the job, renders the progress events with a timer, and plays the finished film with the same renderer code the MP4 export uses.
- **Rendering on the server** (MP4 for download or sharing only) needs Playwright with Chromium and ffmpeg, so the host must run a container.
- **Cache:** reviewed research is kept by Wikidata id plus language, and a fresh film is reused from its folder for a week, so a known object opens at once. Only research results and paintings are cached, never the visitor's photo or location.
- **Modal uploads:** out/cache, samples and .env.local never go into the image; Modal has no ignore file, so the Image definition excludes them with ignore patterns. The web job starts with an empty cache or one seeded only from the reviewed demo objects.
- **Hosting: Modal, TEST on day 4.** A Modal account exists (workspace `debarbanson`), and the hackathon's $100 Modal credits were requested on 26 Oct (selected teams only, not guaranteed). Modal authenticates through its own CLI (`modal token new`, stored outside the repo), and the app's keys go into Modal secrets, never into the repo. Fallback: another container host. It must stay up through judging (5 to 9 November).
- **Limits for a public link:** reviewed example films for everyone, plus a limited "Try your own". One budget authority admits each film (per-visitor limit, daily quota) and reserves a ceiling before every billable call, reconciling after; it fails closed when accounting is unavailable. Meta's "Spend Limit" is only an alert and does not stop billing (hackathon FAQ, 26 Oct), so the app itself refuses new films past the quota; past the $150 credits, usage is charged to the card.

## Privacy

- No accounts, no cookies, no analytics.
- The photo is normalised at upload (orientation applied, metadata stripped) and kept for the job's duration plus 24 hours, then deleted. Coordinates never touch disk or outputs: lookups run in memory and error text carries no query strings.
- The page says this in one line under the upload button.

## Out of scope

Sharing links, galleries, user history, payments.
