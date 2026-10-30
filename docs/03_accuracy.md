# 03 Accuracy and content rules

## No source, no claim

1. Every caption in a film comes from a claim with at least one `url_citation`.
2. Every claim passes the verification step: the source text must support the complete claim. Unsupported and partly supported claims are dropped; "partly" means no. Every accepted claim rests on a literal quote inside a page we fetched, bound to that page's URL. Search snippets are never evidence.
3. **Source quality.** Encyclopedias (Wikipedia, Wikidata), heritage registers, official sites of the object or its owner or municipality, newspapers, archives and books count as sources. User-written and aggregator sites (review sites such as Tripadvisor, place and booking aggregators such as AroundUs and GetYourGuide, forums, social media) may confirm a claim but never stand alone as its only source.
   - **Quality is judged on the sources that support the claim,** not on every source listed. A claim whose supporting text is found only on a weak source (for example the water tower's 1990 storm, found only on Tripadvisor) is not verified, even if a good source is also listed.
   - **A plan, promise or attempt is not an event.** "Haarlem took on the duty to rebuild in 1963; nothing happened" means the mill stayed a ruin. Only completed changes (built, burnt, demolished, restored, rebuilt, repurposed) change the object's state; plans and attempts may be captions, never states.
4. Dates are only as precise as the source. "Around 1850" stays "around 1850".
5. The source of each caption is shown on screen while it plays (site name) and in full on the end card.
6. `research.json` keeps every claim, its sources and its verdict, so a film can be checked afterwards.
7. **Too little is an answer, not a gap to fill.** Below the thresholds in step 3b of the pipeline, the user gets a shorter film or no film, never invented filler. What a user tells us themselves is shown as "told by <name>" and never counted as verified.

## What the paintings may show

- The painted eras are illustrations, not documents. The end card says so: "Scenes are AI-generated illustrations based on the sources listed."
- Scene details (dress, transport, surroundings) follow the era in general; specific events are only depicted when a verified claim names them.
- **The object is shown in its verified state for each era.** If it burned, it is shown burnt; if it was rebuilt, the rebuilt form appears from that year. With no sourced change, it keeps the form of the previous era. Each painting is checked against that state and the final caption before it is used.
- Each final scene carries an immutable evidence reference (claim, URL, quote); the renderer refuses a scene without one. A caption sentence counts only when fully supported, rechecked after every rewrite.
- The film ends on the user's own photo, the only photographic image in it.

## Excluded content

- **War and politics are never the theme.** The hackathon rule excludes projects about war or politics; The Witness is about places. A sourced, factual mention is allowed (for example "a war memorial was placed beside me in 1950"), but no combat or destruction scenes are painted, no political figures are shown, and an era whose only claims are about war or politics is summarised in one neutral caption or skipped. (Interpretation to confirm in the hackathon Discord #questions.)
- **Living private persons** are never named or depicted.
- **No impersonation and no defamatory images** (Meta Acceptable Use Policy).

## Labelling and provenance

- Each film carries a visible "AI-generated imagery" label on the end card.
- Meta's provenance signals on generated images are never removed ([Acceptable Use Policy](https://dev.meta.ai/legal/acceptable-use-policy)).
- Reference images are planned, not built. When built: public domain, CC0 or CC BY only. CC BY images are credited by author, licence and link on the end card. Never CC BY-SA (share-alike could bind the film's own licence), NC or ND, and never an image without a clear licence.

## Choosing demo subjects

Any notable object works: a windmill, a water tower, a church, a lighthouse, an old tree. For the demo, pick objects whose own life changed visibly (built, extended, burnt, rebuilt, repurposed) and whose history is not mainly about conflict. Daytime photos make the best closing shot.
