# 08 Picture-book version

You must be 18 or older to upload a photo.

Uploads make the film only. Two of the three examples also carry a picture-book version: the same checked facts in simpler words, with picture-book paintings from the same anchor. Same object, same checked facts, told differently. De Adriaan is documentary-only: two of its picture-book paintings failed revalidation (see eval/example_revalidation_2026-11-04.json). The spot-the-difference game is built and appears only with 3 or more grounded changes; none of the three examples qualifies, so the submission ships no game.

## The rule that does not change

**Simple, but still true.** The picture-book version uses exactly the checked claims of the documentary version. Nothing is added, nothing is guessed, no detail is made more exciting than the source says. Every picture-book caption is a rewrite of a checked claim and goes through verification again (step 3): it must still be supported by the same source sentence. A rewrite that fails is replaced by a plainer one or dropped.

It is not an education chatbot (an anti-project in the hackathon rules): there is no free conversation, only the film and the sources.

## What changes in the picture-book version

| Part | Documentary | Picture-book |
|---|---|---|
| Captions | First person, factual, up to 2 lines | First person, short sentences, everyday words, one idea per caption ("I was opened.") |
| Painting style | Watercolour, period-accurate | Warm picture-book illustration, same anchor and same composition, so the object is recognisably the same |
| Heavy moments | Stated plainly | Stated gently but truthfully ("In 1932 I caught fire and only my base was left."); no frightening scenes painted |
| War and politics | One neutral sourced line at most | Left out entirely |
| End of the film | Sources and AI label | Sources and AI label ("Spot the difference" appears only with 3 or more grounded changes) |

## Spot the difference: then and now

After the film, one painted era is shown next to the photo of today, above covered cards. Each card hides one checked change; tap it to reveal the change in words ("Found 2 of 4."). The game appears only with 3 or more grounded changes; none of the three examples qualifies, so the submission ships no game.

1. **Pick the pair:** the filmed era whose checked state differs most from today in visible ways: the starkest contrast wins.
2. **Find the differences (Muse Spark, vision):** `muse-spark-1.3` gets both images and returns 3 to 5 differences, each naming the checked state change it shows, quoted exactly.
3. **Check them:** a difference may only describe what is visible in both images; differences in the object itself must match its checked state for that era (step 5). Anything unverifiable is dropped, and fewer than 3 grounded changes means no game.
4. **Play:** spot a change in the pictures, then tap its card to reveal it.

## Pipeline changes

- **Step 2/3:** after verification, write the picture-book captions from the checked claims, then verify each again against its source sentence.
- **Step 4:** paint a second set from the same anchor with picture-book style words, from the same checked states. Both versions are cached.
- **Step 5:** the visual check applies to the picture-book paintings too.
- **New step 5b:** spot the difference, as above.
- **Step 7:** the renderer takes an audience setting (`adult` or `child`) for captions, style and the ending.

## On the web page

- A switch on the finished example films: "Documentary / Picture-book". It loads the sibling film in the other version.
- The spot-the-difference game, where it appears, runs in the browser as covered cards to tap.

## In the demo

- 15 seconds of the same object, documentary and picture-book version side by side.
- Closing line, "what's next": the **witness hunt**, a walk that finds the notable objects within 500 m (step 0 already knows them) and collects a film for each one photographed.

## Planned work

Spot the difference as flip cards: each card asks what changed between a painted era and today's photo. Tap it to flip it and see the answer with its source. It's shown only when at least three checked changes exist.

## Time budget

The picture-book captions and paintings are made after the documentary ones, from the same anchor, so they add their own painting time on top of the targets in docs/02_pipeline.md. Spot the difference adds one vision call (about 10 s) after the paintings.
