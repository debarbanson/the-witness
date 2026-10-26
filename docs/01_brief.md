# 01 Brief

## The problem

Every town has objects that have stood through centuries: a windmill, a church tree, a lighthouse, a bridge-keeper's house. People walk past them daily and know nothing of what they have seen. The history exists, scattered across archives, municipal pages and heritage registers, but nobody turns it into something a passer-by would watch.

Heritage societies and local historians have the knowledge but no time or budget for film. A one-minute, sourced, beautiful film per object, made from one photo, changes that.

## Who it is for

- **Local heritage societies and municipalities:** a film per monument, linked from a QR plaque or the heritage register.
- **Visitors and families:** "what has this tree seen?" answered on the spot, honestly sourced.
- **Teachers and guides:** a starting point that shows its sources, so it can be checked and extended.

## Why this fits "Build for Your World"

The maker lives in the Netherlands, surrounded by centuries-old windmills, trees and lighthouses whose stories are written down in archives but rarely seen by the people who pass them. The Witness is a tool anyone can point at the object in front of them.

## What makes it more than an image generator

1. **Research with receipts:** every caption is backed by a URL the viewer can see, and claims that cannot be verified are dropped.
2. **The object's own history is shown truthfully:** built, extended, burnt, rebuilt, each state is a sourced claim, and every painted era is checked against it.
3. **A consistent series:** the eras are painted as one chained conversation anchored on the user's photo, so the film feels like one place through time, ending on the real photo as "today".
4. **Open knowledge, worldwide and free:** the object is found through OpenStreetMap and Wikidata, its dated facts come from Wikidata, and real historical photos (public domain, CC0 or CC BY with credit, from Wikimedia Commons and Europeana) guide the paintings. Any object, in any country, in any language.
5. **A finished film:** layered parallax, first-person captions and citations, ready to share.

## Out of scope for the hackathon

- Voice narration (no Meta text-to-speech model; captions carry the story).
- Accounts, hosting, payments.
- Objects whose history is mainly war or politics (excluded by rule and by design).

## Success for the demo

- Three films from three real photos (a windmill, an old tree, a lighthouse), each 40 to 60 seconds.
- Every caption has a working source link, shown on screen and in an end card.
- In every era the object matches its verified state for that year (for example De Adriaan: built 1779, burnt 1932, rebuilt 2002).
- Generated in under 10 minutes per film, for under $1 in API cost.
