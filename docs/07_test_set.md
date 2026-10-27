# 07 Test set: 10 international objects

Probed 26 October 2026 with `identify` and `research --place ... --lang en`
on one Wikimedia Commons photo each (CC0, public domain or CC BY). Photos
live in `samples/` (git-ignored); each is reproducible from its file page.

## Photos

| Object | Commons file | Licence |
|---|---|---|
| rubjerg-knude | [file](https://commons.wikimedia.org/wiki/File:Rubjerg_Knude_in_December_2009_ubt.JPG) | CC BY 4.0 |
| kintai-bridge | [file](https://commons.wikimedia.org/wiki/File:Iwakuni,_ponte_kintai-kyo,_03,0.jpg) | CC BY 3.0 |
| major-oak | [file](https://commons.wikimedia.org/wiki/File:Major_Oak.JPG) | CC BY 3.0 |
| brooklyn-bridge | [file](https://commons.wikimedia.org/wiki/File:Pont_de_Brooklyn_de_nuit_-_Octobre_2008_edit.jpg) | CC BY 3.0 |
| christ-redeemer | [file](https://commons.wikimedia.org/wiki/File:Christ-Redeemer-Rio-de-Janeiro.jpg) | CC BY 4.0 |
| biosphere | [file](https://commons.wikimedia.org/wiki/File:Biosphere_-_Panorama.jpg) | CC BY 2.0 |
| eiffel-tower | [file](https://commons.wikimedia.org/wiki/File:Eiffel_Tower_blue_skies_(Unsplash).jpg) | CC0 |
| djenne-mosque | [file](https://commons.wikimedia.org/wiki/File:Djenne_Mosque_Dubois_1911.jpg) | Public domain |
| sydney-opera | [file](https://commons.wikimedia.org/wiki/File:MC_Sydney_Opera_House.jpg) | CC BY 2.5 |
| raffles-hotel | [file](https://commons.wikimedia.org/wiki/File:Singapore_Raffles_Hotel_1.JPG) | CC0 |

CC BY photos are credited here by licence and link; the author credit travels
with the film's `sources.md` when a photo is used. The Djenné photo (Dubois,
1911) predates the current mosque's 1930s form; the Eiffel Tower photo is a
modern CC0 shot.

## Results (re-run, 26 October, evening)

All 12 objects (the 10 below plus De Adriaan and the water tower)
re-ran clean after the accuracy, speed and bug fixes: 10 full films,
1 short film (Brooklyn Bridge), 1 too little (the water tower).
`identify` plus `research --place ... --lang en`; per-object logs in
`out/testset/` (git-ignored), outputs in `out/<qid-slug>/research.json`.

Timings are seconds per step: identify / Wikidata facts / research /
source fetch / verify / total. Targets from "Time budget per film" in
docs/02_pipeline.md: object recognised within 15 s; the story (facts
plus research plus fetch plus verify) within 60 s of confirming;
research as a whole in 2 to 3 minutes.

| Object | Outcome | Ident | Facts | Resrch | Fetch | Verify | Total | Story | Budget |
|---|---|---|---|---|---|---|---|---|---|
| rubjerg-knude | full (10v, 7e, 5g) | 47.8 | 0.6 | 34.7 | 175.4 | 19.7 | 278.2 | 230 | miss, miss |
| kintai-bridge | full (10v, 4e, 6g) | 97.0 | 0.7 | 26.5 | 159.9 | 19.0 | 303.1 | 206 | miss, miss |
| major-oak | full (10v, 10e, 6g) | 31.1 | 0.5 | 50.5 | 94.7 | 20.8 | 197.5 | 166 | miss, miss |
| brooklyn-bridge | short (10v, 10e, 4g) | 49.0 | 0.6 | 38.2 | 9.2 | 18.0 | 115.1 | 66 | miss, near |
| christ-redeemer | full (12v, 10e, 4g) | 42.0 | 0.7 | 28.5 | 31.7 | 19.0 | 121.8 | 80 | miss, miss |
| biosphere | full (10v, 9e, 5g) | 77.9 | 0.6 | 42.3 | 297.3 | 16.9 | 435.1 | 357 | miss, miss |
| eiffel-tower | full (10v, 9e, 4g) | 83.3 | 0.8 | 32.8 | 1.6 | 25.3 | 143.8 | 61 | miss, met |
| djenne-mosque | full (8v, 7e, 4g) | 49.5 | 0.5 | 52.3 | 26.2 | 26.7 | 155.3 | 106 | miss, miss |
| sydney-opera | full (13v, 9e, 7g) | 40.5 | 0.7 | 53.0 | 307.6 | 26.6 | 428.4 | 388 | miss, miss |
| raffles-hotel | full (10v, 9e, 5g) | 45.3 | 0.6 | 33.1 | 15.8 | 23.1 | 118.0 | 73 | miss, near |
| de-adriaan | full (11v, 9e, 3g) | 98.0 | 0.5 | 40.3 | 5.2 | 19.4 | 163.4 | 65 | miss, near |
| water-tower | too little (1v, 1e, 1g) | 68.9 | 0.0 | 30.6 | 5.6 | 21.0 | 126.1 | 57 | miss, met |

v = verified claims, e = eras, g = good sources. "Budget" judges the
15 s identify target, then the 60 s story target. Research as a whole
met 2 to 3 minutes for 7 of 12 (brooklyn, christ, eiffel, djenne,
raffles, de-adriaan, tower); the oak was near at 197 s; rubjerg,
kintai, biosphere and sydney missed on source fetching (P12).

### Per object

**rubjerg-knude** (Q2206180). Langs read: nl, en (Danish not read,
P8). Claims: 1899 inception, 2019 relocation, 1899 and 1900 built,
1968 repurposed, 2002 and 2009 damage, 2009 outbuildings removed,
2016 restored, 2019 moved, all supported. Timeline: standing
1899-1968; repurposed to 2002; damaged to 2009; "burnt, only the
base left" 2009-2016 (wrong, P5); restored to 2019; moved since.
Scenes: 6 plus today.

**kintai-bridge** (Q1196460). Langs read: en only (no Japanese, P8).
Claims: 1673 built, 1674 washed away and rebuilt, 1950 typhoon
washout, 1953 rebuilt, 2001-2004 restored, all supported; a 1950
"demolition" duplicate unsupported. Timeline: standing 1673-1674;
rebuilt to 1950; damaged to 1953; rebuilt to 2004; restored since.
Scenes: 5 plus today.

**major-oak** (Q388443). Langs read: nl, en. Claims: 1026 "built"
from an 800-1200 year age estimate (too precise, P10); 1790 renamed;
1908 chains; 1960s concrete fill; 1970s scaffolding; 1974 fences;
1982 fire; 2022 heat damage; June 2026 RSPB death announcement, all
supported, plus a P18 image claim. Legend correctly absent: no
Robin Hood claim verified. Timeline: standing 1026-1790; repurposed
to 1890; "the major oak c. 1890.jpg" 1890-1908 (wrong, P4);
restored to 1982; "burnt, only the base left" to 2022 (overstated,
P6); damaged since. Scenes: 6 plus today. The 2026 quote came from
secretgb.co.uk though Wikipedia also supports it (P11).

**brooklyn-bridge** (Q125006). Langs read: nl, en. Claims: 1869
construction plus five heritage designations supported; 1901 and
1981 cable snaps, 1953 widening, 2021 bike path supported; the 1883
built claim and six more stayed unverified (choose-before-check
spares, P7), so build_year is false and the outcome is short_film.
Timeline is mostly designations as states (P4). Scenes: 6 plus
today.

**christ-redeemer** (Q79961). Langs read: nl, en (no Portuguese,
P8). Claims: 1920 inception partly; 1926 start, 1931 completion,
1922 foundation stone, 1931 opening, 1980 and 1990 restorations,
2003 escalators, 2006 chapel, 2008 lightning supported; 2010
restoration and vandalism and 2014 lightning unverified. Timeline:
standing 1920-1926 (before construction, P15); start of
construction to 1931; standing to 1980; restored to 2003; extended
to 2006; repurposed to 2008; damaged to 2014; "lightning strike"
since (P13). Scenes: 6 plus today.

**biosphere** (Q864789). Langs read: en only (no French, P8).
Claims: 1965-1967 built, 1968 donated, 1971-1972 uses, 1976 fire,
1995 museum, 1998 ice storm, 2007 environment museum supported;
1973, 1990, 2021 unverified. All quotes came from en.wikipedia:
three other sources timed out (P12). Timeline: standing 1965-1968;
repurposed to 1976; "burnt, only the base left" to 1995
(overstated, P6); rebuilt to 1998; damaged to 2007; repurposed
since. Scenes: 6 plus today.

**eiffel-tower** (Q243). Langs read: nl, en (no French, P8). Claims:
25 found; 1887-1889 built, 1900 lifts, 1937 modernisation, 1946
lifts, 1967 move proposal, 2022 antenna supported; 1986 names
partly; the 1909 dismantling plan, the 1940 closure and the 1944
demolition order stayed unverified and never became states. The
1967 proposal is supported but correctly caption-only, never a
state. Timeline: standing 1887-1900; rebuilt to 1946; restored to
1964; "monument historique inscrit" to 1986 (P4); restored to
2009; "tour eiffel wikimedia commons.jpg" to 2022 (P4); extended
since. Scenes: 6 plus today.

**djenne-mosque** (Q683632). Langs read: nl, en (no French, P8).
Claims: all 8 supported: 1280 first mosque, 1830 damaged, 1834
second mosque, 1906-1907 rebuilt, 2009 Aga Khan restoration, 2016
rain damage. No recent-conflict claim appeared; the war rule had
nothing to filter. The yearly replastering was not researched.
Timeline: 7 clean segments. Scenes: 6 plus today.

**sydney-opera** (Q45178). Langs read: nl, en. Claims: 13
supported, incl. 1959-1973 construction, 1973 opening, 2004 Utzon
room, 2009 foyer, 2022 works; three designations; 2003 "No War"
paint vandalism partly, kept as a damaged state (P14). Timeline:
"peter hall" 1966-1973 (architect as state, P4) and three
designation states (P4) alongside the real ones. Scenes: 6 plus
today.

**raffles-hotel** (Q1538837). Langs read: nl, en. Claims: 1887
built, 1890-1920 extensions, 1899 main building, 1942 wartime
rename, 1987 monument, 1989 renovation supported; 1923, 1945, 2019
unverified. The 1942 rename carries a 45-year "repurposed" scene
(P14). Timeline: 8 segments, clean apart from "designated" and
"renovation" states. Scenes: 6 plus today.

**de-adriaan** (Q2763574). Langs read: nl, en (local correct).
Claims: 11 supported, incl. 1779 built, 1802 sold, 1865 steam,
1925 bought, 1930 storm, 1932 burnt, 1999 rebuild start, 2003
museum; 2002 reopening and 2004 weddings unverified. The 1963
"restored" claim ("promise fell into oblivion, nothing happened")
was marked completed:true, so the timeline wrongly shows restored
1963-1999 instead of burnt 1932-1999 (P3). Timeline otherwise
clean, incl. under reconstruction 1999-2003. Scenes: 6 plus
today (1865 extended and 1963 restored folded into caption lines).

**water-tower** (Q2487636). Langs read: nl only (local correct).
Claims: only 1932 built supported; 1977 disused, 1987 out of use,
1990 storm and 1991 new tulips unsupported (weak sources only, as
designed for 1990); 1986 tulips unsupported despite quoting the
nl.wikipedia sentence that states it (false negative, P2). The
smoke run gave short_film (3 verified); this run gives too_little
(1 verified): research and the verifier flap between runs (P1).
Timeline: standing 1932-now. Scenes: 1 plus today.

### Review expectations, checked

- A1 tower 1986 tulips via nl.wikipedia: failed in this run (P2);
  passed in the earlier smoke run. A1 tower 1990 storm no longer
  verified: passed (weak sources only).
- A2 De Adriaan burnt 1932-1999: failed (P3). A2 Eiffel dismantling
  never a state: passed.
- A3 scene choice: passed everywhere (at most 7 scenes, today last,
  reasons and caption lines stored).
- C9 Nominatim retry: christ-redeemer identified cleanly (42 s).
- C10 slugs: all 12 outputs under qid slugs (no more `film` or
  `biosph-re`). C11 `--lang en`: labels now English, but nl
  articles are still fetched everywhere (P8).

## Problems found (not fixed yet)

- P1. Run-to-run flapping: the tower gave short_film then
  too_little; research returns different lifespan events and the
  verifier flips on 1986/1987. A demo subject must not flap.
- P2. Verifier false negative: tower 1986 tulips unsupported while
  quoting the nl.wikipedia sentence that states it.
- P3. Verifier marks failed attempts completed: De Adriaan 1963
  ("promise fell into oblivion") is completed:true, giving a false
  restored 1963-1999 state.
- P4. Non-states become states and scenes: Wikidata image filenames
  (eiffel, oak), architect names (sydney "peter hall"), heritage
  designations (brooklyn, eiffel, sydney). Only physical changes
  may become states.
- P5. Rubjerg false "burnt, only the base left" 2009-2016:
  demolished outbuildings are not a burnt lighthouse. Demolished
  is not burnt, and parts are not the object.
- P6. "Burnt, only the base left" overstates partial fires:
  biosphere 1976 (steel frame survived), oak 1982 (tree survived).
- P7. Brooklyn short_film: the 1883 built claim was never checked,
  so build_year is false. Anchor and build claims must always be
  verified, spares or not.
- P8. Local languages never read: sitelinks and labels hardcode an
  nl fallback instead of using read_langs(), so Kintai read no
  Japanese, Biosphere no French, Christ no Portuguese, Eiffel and
  Djenné no French, Rubjerg no Danish.
- P9. Raw Wikidata timestamps reach captions ("in 1967 inception:
  +1967-01-01T00:00:00Z"). Format them ("built 1967").
- P10. False precision: oak "built 1026" from an 800-1200 year age
  estimate, against rule 4 of docs/03_accuracy.md.
- P11. Quote preference: oak 2026 quotes secretgb.co.uk though
  en.wikipedia also supports it. Prefer the good-source quote.
- P12. Fetch dominates runtime: the 90 s plain-GET timeout cost
  biosphere and sydney ~300 s each on three timeouts; identify
  takes 31-98 s against a 15 s target. Lower the timeout, fetch
  plain pages in parallel (only Wikimedia, Overpass and Nominatim
  are one-at-a-time), find what is slow in identify.
- P13. Event labels as scene states ("lightning strike", "start of
  construction", "renovation", "designated") are not paintable
  states; map them before painting.
- P14. War and politics borderlines carry scenes: the Raffles 1942
  rename (45 years) and the Sydney 2003 "No War" vandalism. Allowed
  as factual mentions, but review whether whole scenes may hinge
  on them.
- P15. Partly claims seed states: christ "standing" 1920-1926 comes
  from a partly inception claim predating construction.

## Provider comparison: Meta vs Muse Spark Open (27 October)

Passage-only support checks ran on both providers over identical jobs
(same claims, same passages): the 6 fixed regression claims, then all
12 test objects (`--verify-with both`). Completion and the web-search
fallback stayed on Meta for both sides.

- Regressions: 6/6 agreement (meta 40 s, open 35 s).
- 12 objects: 127/133 agreement (95.5%). Per object: biosphere 10/11,
  brooklyn 11/11, christ 14/14, de-adriaan 12/12, djenne 9/10, eiffel
  10/11, kintai 12/13, oak 9/9, raffles 11/12, rubjerg 12/12, sydney
  12/12, tower 5/6.
- False negatives are symmetric: Open missed Eiffel 1887 built (Meta
  partly, both quoting the evidence), Meta missed Biosphere 1967 built
  (Open partly, quoting it). The other four disagreements are
  supported-vs-partly washes with the same quote.
- Time (verify phase, 12 objects): meta 750 s, open 797 s; per object
  mixed either way. The first Baseten call took about 10 min (cold
  start); later calls averaged about 2 s.
- Tokens: baseten support-only 1.63 M (367 k in, 1.26 M out; the model
  always reasons, and reasoning counts as output); meta whole pipeline
  2.87 M (2.09 M in, 0.78 M out).
- Cost: baseten support $2.04 for 12 films ($0.17 each) at $1.25 per M
  input and output tokens; meta full pipeline $5.94 ($0.50 each) at
  $1.25 in and $4.25 out. The $100 Baseten grant covers about 590
  films of support checks.

Decision: support checks default to Muse Spark Open on Baseten, with
silent Meta fallback per call (180 s timeout) as demo insurance;
research, vision, search fallback and completion stay on Meta.
`--verify-with meta` overrides per run.

## Fit for the children's version

Not built; scheduled Wed-Thu after the painting. What this round
put in place: `research.json` already holds, per scene, the state
plus caption lines with their claim year and text, and per claim
the quote, source URL and verdict. Children's captions fit there as
a rewrite next to each adult caption line (same claim, same quote),
re-verified against that quote per docs/08_children.md; the
audience setting (`adult` or `child`) will run from research
through captions, painting, the check and the renderer, with both
versions cached together.
