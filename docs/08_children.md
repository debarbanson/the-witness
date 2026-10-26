# 08 For children

Every film can be made for two audiences: adults, and children aged 8 and up. Same object, same verified facts, told differently. This is part of the product, not an extra: families, schools and museum visitors are a large part of who stands in front of old objects.

## The rule that does not change

**Simple, but still true.** The children's version uses exactly the verified claims of the adult version. Nothing is added, nothing is guessed, no detail is made more exciting than the source says. Every children's caption is a rewrite of a verified claim and goes through verification again (step 3): it must still be supported by the same source sentence. A rewrite that fails is replaced by a plainer one or dropped.

It is not an education chatbot (an anti-project in the hackathon rules): there is no free conversation, only the film, the game below and the sources.

## What changes in the children's version

| Part | Adults | Children (8+) |
|---|---|---|
| Captions | First person, factual, up to 2 lines | First person, short sentences, everyday words, one idea per caption ("I was built in 1779. There were no cars then, only horses and carts.") |
| Painting style | Watercolour, period-accurate | Warm picture-book illustration, same anchor and same composition, so the object is recognisably the same |
| Heavy moments | Stated plainly | Stated gently but truthfully ("In 1932 I caught fire and only my base was left."); no frightening scenes painted |
| War and politics | One neutral sourced line at most | Left out entirely |
| End of the film | Sources and AI label | "Spot the difference" (below), then sources and AI label |

## Spot the difference: then and now

After the film, one painted era is shown next to the user's own photo of today: "Find 5 things that changed!"

1. **Pick the pair:** the era whose painting differs most from today in visible ways (transport, lighting, clothing, buildings), preferring an era before 1950.
2. **Find the differences (Muse Spark, vision):** `muse-spark-1.3` gets both images and returns up to 5 differences, each with a short child-friendly label and the approximate region in each image (normalised boxes).
3. **Check them:** a difference may only describe what is visible in both images; differences in the object itself must match its verified state for that era (step 5). Anything unverifiable is dropped.
4. **Play:** the child taps where they see a change; a found difference lights up in both images with its label. "Show me" reveals the rest.

## Pipeline changes

- **Step 2/3:** after verification, write the children's captions from the verified claims, then verify each again against its source sentence.
- **Step 4:** paint the children's eras from the same anchor with the picture-book style words (TEST: one style chain or a restyle of the adult paintings, whichever keeps the object more consistent). Both versions are cached.
- **Step 5:** the visual check applies to the children's paintings too.
- **New step 5b:** spot the difference, as above.
- **Step 7:** the renderer takes an audience setting (`adult` or `child`) for captions, style and the ending.

## On the web page

- A switch on the start screen and on the finished film: "For adults / For children". Switching after the film is made shows the other version as soon as it is ready (both are made together, so usually at once).
- The spot-the-difference game runs in the browser, works with taps on a phone, and needs no account.

## In the demo

- 15 seconds of the same object for adults and for children, side by side.
- A child (or a hand) playing spot the difference on a phone.
- Closing line, "what's next": the **witness hunt**, a family walk that finds the notable objects within 500 m (step 0 already knows them) and collects a film for each one photographed.

## Time budget

The children's captions and paintings are made in parallel with the adult ones, so the targets in docs/02_pipeline.md stay the same. Spot the difference adds one vision call (about 10 s) after the paintings.
