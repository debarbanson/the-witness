# 01 Brief

## The problem

Every town has objects that have stood through centuries: a windmill, a church tree, a lighthouse, a bridge-keeper's house. People walk past them daily and know nothing of what they have seen. The history exists, scattered across archives, municipal pages and heritage registers, but nothing turns it into a sourced film of painted changes that returns to your own photo. Similar products exist (Talking Statues, Monumoir); the sourced, painted changes are the difference.

Heritage societies and local historians have the knowledge but no time or budget for film. A short, sourced, beautiful film per object, made from one photo, changes that.

## Who it is for

- **Local heritage societies and municipalities:** a film per monument, linked from a QR plaque or the heritage register.
- **Visitors:** "what has this tree seen?" answered on the spot, honestly sourced.
- **Teachers and guides:** a starting point that shows its sources, so it can be checked and extended.

## Why this fits "Build for Your World"

The maker lives in the Netherlands, surrounded by centuries-old windmills, trees and lighthouses whose stories are written down in archives but rarely seen by the people who pass them. The Witness is a tool anyone can point at the object in front of them.

## What makes it more than an image generator

1. **Research with receipts:** every caption is backed by a URL the viewer can see, and claims that cannot be verified are dropped.
2. **The object's own history is shown truthfully:** built, extended, burnt, rebuilt, each state is a sourced claim, and every painted era is checked against it.
3. **A consistent series:** every era branches in parallel from one anchor turn on the user's photo, so the film feels like one place through time, ending on the real photo dated with its own photo year. Parallel beat the serial chain on De Adriaan (6 of 6 eras in 79 s against 5 of 6 in 195 s, 0.3% framing drift against 3.6%).
4. **Open data, worldwide sources:** the object is found through OpenStreetMap and Wikidata, and its dated facts come from Wikidata and Wikipedia in any language. Sources may be in any language; captions are English only. The data sources are free; generating a film and hosting the page cost money. (Automatic reference photos from Commons or Europeana are planned, not built.)
5. **A finished film:** first-person captions and citations in a browser player with pause and replay, shared as an unlisted public page on Modal plus this repo. (MP4 export runs from the command line; a download button on the page is planned, not built.)

## Two versions

Uploads make the film only. Two of the three examples also carry a picture-book version: the same checked facts in simpler words with picture-book paintings. De Adriaan is documentary-only: two of its picture-book paintings failed revalidation. Both need enough verified material. Simple, but still true: every picture-book caption is verified again. The "spot the difference" game is built and appears only with 3 or more grounded changes; none of the three examples qualifies. Details: [08_picture_book.md](08_picture_book.md).

## Out of scope for the hackathon

- Voice narration (no Meta text-to-speech model; captions carry the story).
- Accounts, payments. (Hosting is in scope: the submission is an unlisted public page on Modal.)
- Objects whose history is mainly war or politics (excluded by rule and by design).
- Figure layers, streaming playback, non-English captions, reference images, longer films: see "Planned, not built" in the README.

## Success for the demo

- Three films from three real photos (a windmill, an old tree, a lighthouse), each about 30 to 37 seconds.
- Every caption has a working source link, shown on screen and in an end card.
- In every era the object matches its verified state for that year (for example De Adriaan: opened 1779, burnt 1932, rebuilt 2002).
- Generated in minutes per film, for under $1 in API cost: one staging film measured 2 Nov took about 8 minutes wall time (Identify 33 s, Research 49 s, Check 91 s, Paint 272 s, Film 3 s) at a $1.03 model-API ledger delta ($0.52 on the film job). The goal stays a few minutes and under $1; the owner's phone films re-measure after the later speedups.
