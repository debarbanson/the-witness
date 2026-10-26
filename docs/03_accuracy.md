# 03 Accuracy and content rules

## No source, no claim

1. Every caption in a film comes from a claim with at least one `url_citation`.
2. Every claim passes the verification step: the source text must support it. Unsupported claims are dropped, partly supported ones are rewritten to what the source says.
3. Dates are only as precise as the source. "Around 1850" stays "around 1850".
4. The source of each caption is shown on screen while it plays (site name) and in full on the end card.
5. `research.json` keeps every claim, its sources and its verdict, so a film can be checked afterwards.

## What the paintings may show

- The painted eras are illustrations, not documents. The end card says so: "Scenes are AI-generated illustrations based on the sources listed."
- Scene details (dress, transport, surroundings) follow the era in general; specific events are only depicted when a verified claim names them.
- The object itself is never generated: it is the user's photo, composited into every era.

## Excluded content

- **War and armed conflict, and political events or figures.** Hackathon rule ("anything political or involving war") and a design choice. Eras whose only verified claims are about war or politics are skipped; the film moves to the next era.
- **Living private persons** are never named or depicted.
- **No impersonation and no defamatory images** (Meta Acceptable Use Policy).

## Labelling and provenance

- Each film carries a visible "AI-generated imagery" label on the end card.
- Meta's provenance signals on generated images are never removed ([Acceptable Use Policy](https://dev.meta.ai/legal/acceptable-use-policy)).
- Reference images are public domain only, with their source listed in `sources.md`.

## Choosing demo subjects

Pick objects with a peaceful, well-documented history: a Dutch windmill, a centuries-old tree, a lighthouse. Check the first research pass before rendering: if most claims are about conflict, choose another subject.
