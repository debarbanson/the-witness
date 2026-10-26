# 06 The web page

The judges score "does the product hold up live", so the pipeline gets a small mobile web page. No app store: a link that works on any phone.

## The flow

1. **Open the link** on a phone. One screen: "Point me at something old."
2. **Take or pick a photo.** `<input type="file" accept="image/*" capture="environment">` opens the camera on phones.
3. **Location.** If the photo carries GPS data, use it. If not, ask the browser (`navigator.geolocation`, with a one-line reason). If refused, a text field: "Where is it?"
4. **Confirm the object.** Step 0 shows its best match: "Is this De Adriaan, Haarlem?" with the OpenStreetMap name and distance. Yes, or "something else" with a text field.
5. **Watch it being made.** A progress view that shows the real steps as they happen: sources found, claims verified or dropped, eras painted, a painting checked and redone. This is part of the show, not a spinner.
6. **The film.** Plays inline, vertical, with a download button and the source list below it.
7. **When there is too little** (pipeline step 3b): a short film, or a single card with the verified facts and two buttons, "Add a source" (paste a link) and "Tell what you know" (record or type; shown as "told by", never as fact).

## How it is built

- **Back end:** Python, a small FastAPI app around the same `witness` package the command line uses. A film takes minutes, so `POST /films` starts a job and returns its id; `GET /films/{id}` returns its progress events and, at the end, the film and sources.
- **Front end:** one static HTML page with plain JavaScript, no framework. It polls the job and renders the progress events.
- **Rendering on the server** needs Playwright with Chromium and ffmpeg, so the host must run a container.
- **Hosting: TEST on day 4.** Candidates: Modal (Python containers; the hackathon offers $100 in credits, not guaranteed), or another container host. It must stay up through judging (5 to 9 November).
- **Limits for a public link:** one film at a time per visitor, a daily cap on films, and a spend limit on the API key, so the credits cannot be drained.

## Privacy

- No accounts, no cookies, no analytics.
- Photos and coordinates live only for the job's duration plus 24 hours, then are deleted. GPS is never written into outputs.
- The page says this in one line under the upload button.

## Out of scope

Sharing links, galleries, user history, payments.
