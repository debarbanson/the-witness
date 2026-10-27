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
| sagrada-familia | [file](https://commons.wikimedia.org/wiki/File:Sagrada_Familia_0110.JPG) | Public domain |
| vasa-ship | [file](https://commons.wikimedia.org/wiki/File:%22Vasa%22,_a_fully_intact_64_gun_warship_from_the_17th_century_that_was_salvaged_(24490197659).jpg) | CC BY 2.0 |
| colosseum | [file](https://commons.wikimedia.org/wiki/File:Colosseum_of_Rome_and_Roman_forum.jpg) | CC0 |
| heidelberg-castle | [file](https://commons.wikimedia.org/wiki/File:Heidelberg_castle_from_vine_growing_area.jpg) | CC BY 4.0 |
| belem-tower | [file](https://commons.wikimedia.org/wiki/File:Lisbon_Bel%C3%A9m_Tower_(470009179).jpg) | CC BY 2.0 |
| atomium | [file](https://commons.wikimedia.org/wiki/File:The_Atomium,_Brussels_-_54578545913.jpg) | CC0 |
| mont-saint-michel | [file](https://commons.wikimedia.org/wiki/File:Mont_St._Michel_Spire.JPG) | Public domain |
| neuschwanstein | [file](https://commons.wikimedia.org/wiki/File:Neuschwanstein_Castle_2024-02.jpg) | CC0 |
| sultan-ahmed-mosque | [file](https://commons.wikimedia.org/wiki/File:2017-09-01_Turkey,_Istanbul_DSC_3669_DxO.jpg) | CC BY 4.0 |
| borobudur | [file](https://commons.wikimedia.org/wiki/File:DSC00096_Java_Centre_Borobudur_Stupas_and_Temple_(6219572675).jpg) | CC BY 2.0 |
| hallgrimskirkja | file page to confirm (EXIF credits G. Edward Johnson, CC-BY) | CC BY (page unverified) |
| hungarian-parliament | file page to confirm (EXIF credits Pierre Blache) | to confirm |

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

## Results (Block 5 re-run, 27 October)

All 12 re-ran with the cache off after blocks 1 to 4, verifying on
Muse Spark Open with Meta fallback: 10 full films, 2 short films
(Eiffel Tower, water tower), zero failures. Per-object logs
`out/testset/*-r3.log` (git-ignored).

| Object | Outcome | Ident | Facts | Resrch | Fetch | Verify | Total | Story | Budget |
|---|---|---|---|---|---|---|---|---|---|
| rubjerg-knude | full (8v, 6e, 6g) | 66.3 | 0.5 | 35.2 | 32.1 | 101.5 | 235.5 | 169 | miss, miss |
| kintai-bridge | full (9v, 5e, 5g) | 71.5 | 0.6 | 35.8 | 19.4 | 53.9 | 181.3 | 110 | miss, miss |
| major-oak | full (6v, 6e, 3g) | 65.9 | 0.4 | 26.1 | 5.3 | 43.3 | 141.0 | 75 | miss, miss |
| brooklyn-bridge | full (9v, 9e, 5g) | 65.6 | 0.7 | 30.2 | 5.5 | 56.6 | 158.7 | 93 | miss, miss |
| christ-redeemer | full (12v, 8e, 7g) | 66.3 | 0.8 | 40.0 | 16.4 | 131.5 | 255.1 | 189 | miss, miss |
| biosphere | full (8v, 8e, 4g) | 65.4 | 0.6 | 21.6 | 5.8 | 87.3 | 180.8 | 115 | miss, miss |
| eiffel-tower | short (7v, 6e, 5g) | 94.7 | 0.9 | 34.7 | 2.1 | 110.9 | 243.3 | 149 | miss, miss |
| djenne-mosque | full (8v, 8e, 6g) | 96.9 | 0.6 | 39.3 | 6.1 | 104.8 | 247.7 | 151 | miss, miss |
| sydney-opera | full (9v, 7e, 8g) | 65.6 | 0.7 | 27.0 | 11.8 | 73.6 | 178.7 | 113 | miss, miss |
| raffles-hotel | full (8v, 7e, 3g) | 64.9 | 0.7 | 31.6 | 5.4 | 77.5 | 180.1 | 115 | miss, miss |
| de-adriaan | full (11v, 9e, 3g) | 66.9 | 0.5 | 27.9 | 15.8 | 82.1 | 193.3 | 126 | miss, miss |
| water-tower | short (4v, 4e, 2g) | 99.4 | 0.5 | 33.2 | 5.2 | 52.3 | 190.6 | 91 | miss, miss |

Story is facts plus research plus fetch plus verify. Identify
misses 15 s on every object: Overpass burns 60 s (two 30 s POST
timeouts) or 90 s (timeouts plus the 30 s 429/502 sleep) and
returns nothing, so every candidate comes from Wikidata nearby;
without Overpass, identify would be about 6 s. Verify now
dominates the story (43 to 132 s): best-of-three over a reasoning
model. Fetch is fixed (1 to 32 s, was up to 300 s). Research as a
whole met 2 to 3 minutes for 7 of 12 (biosphere, brooklyn,
kintai, oak, raffles, sydney, tower); de-adriaan near at 193 s;
christ, djenne, eiffel and rubjerg missed on verify plus
identify.

### Per object

**rubjerg-knude** (Q2206180). Langs read: da, en. Claims: 1899
built, 2019 relocation, 1953 foghorn removal, 1968 end of service,
2002 abandonment, 2016 refit, 2019 move; all supported or partly.
Timeline: under_construction 1899-1953 (wrong: 54 years, P16);
demolished 1953-1968 (foghorn, part scope); standing to 2002;
ruin to 2016; standing to 2019; moved since. Scenes: 6 plus
today. Three plain pages skipped on the 5 s read timeout.

**kintai-bridge** (Q1196460). Langs read: ja, en. Claims: 1673
built, 1674 flood and rebuild, 1950 typhoon washout, 1953
rebuild, 2004 re-timbering; 1674 damage and 2005 typhoon
unsupported. Timeline: standing 1673-1674; ruin to 1950 with
description "bridge re-erected" (condition contradicts the
description, P16); ruin 1950-1953; rebuilt to 2004; rebuilt
since. Scenes: 5 plus today.

**major-oak** (Q388443). Langs read: en. Claims: 1026 age
estimate still too precise (P10, from research wording, not
Wikidata); 1908 chains, 1970s scaffolding, 1974 fences, 1982
fire partly or better; 1960s concrete and 2001 props
unsupported. No Robin Hood legend verified. Timeline: standing
1026-1908; standing with supports to 1982; burnt (partial)
since (P6 fixed). Scenes: 6 plus today.

**brooklyn-bridge** (Q125006). Langs read: en. Claims: 1883
built partly, so the build anchor holds and the film is full
(P7 fixed); five designations supported but caption-only (P4
fixed); 1901 and 1981 cable snaps, 1986 cable replacement,
2021 bike path verified; nine spares unverified. Timeline:
standing 1883-1901; damaged (partial) to 1986;
under_construction to 2021; standing since. Scenes: 6 plus
today.

**christ-redeemer** (Q79961). Langs read: pt, en. Claims: 1926
start, 1931 completion, 1980 and 1990 restorations, 2006
sanctuary, 2008 and 2014 lightning damage and repairs; 1920
inception unsupported, so no more standing-before-construction
(P15 fixed). Timeline: six clean standing segments 1931 to
today. Scenes: 6 plus today.

**biosphere** (Q864789). Langs read: en, fr. Claims: 1967 built
partly, 1968 donation, 1973 conversion, 1976 fire, 1990 funding,
1995 museum, 2007 and 2021 renamings; 1967 inception and 1998
ice storm unsupported. Timeline: standing 1967-1976; burnt
(partial) 1976-1990 (P6 fixed); standing since. Scenes: 6 plus
today.

**eiffel-tower** (Q243). Langs read: en, fr. Claims: 1887 built
unsupported on Open (the known miss; Meta called it partly),
so 7 verified and short_film; 1889 built partly, 1900 lifts,
1918 shell damage, 1940 occupation damage, 1957 mast, 1999
lights, 2024 rings; fifteen spares unverified. The 1909
dismantling plan never a state; no designation or filename
states (P4 fixed). Timeline: standing with a damaged (partial)
1918-1940 segment. Scenes: 6 plus today.

**djenne-mosque** (Q683632). Langs read: en, fr. Claims: 1238
first mosque, 1350 towers, 1819 ruins, 1835 second mosque,
1896 restitution, 1907 rebuild, 2006 roof works; four spares
unverified. No conflict claims; the war rule had nothing to
filter. Timeline: standing 1238-1819; demolished 1819-1835;
standing to 1896; rebuilt to 1906; under_construction twice
(1906-1907 and 1907-2006 did not merge: different
descriptions); standing since. Scenes: 6 plus today.

**sydney-opera** (Q45178). Langs read: en. Claims: 1959 start,
1973 opening, three designations (caption-only), 2004 Utzon
room, 2017 theatre works; no architect-as-state (P4 fixed);
2003 paint vandalism unverified, so P14 untested here.
Timeline: under_construction 1959-1973 (one state for the
decade-plus build); standing since. Scenes: 6 plus today.
Eleven plain pages unreadable (timeouts, 403/404), all via
Wikipedia instead.

**raffles-hotel** (Q1538837). Langs read: en. Claims: 1832
beach house, 1887 hotel, 1890-1899 wings and main building,
2019 renovation; 1904-1923 extensions unsupported; the 1942
wartime rename unverified, so P14 untested here. Timeline:
six clean standing segments. Scenes: 6 plus today.

**de-adriaan** (Q2763574). Langs read: nl, en. Claims: 1779
built, 1802 sale, 1865 steam conversion, 1930 storm, 1932
fire, 1999 rebuild start, 2002 reopening, 2003 museum, 2004
weddings; 1920 electrification unsupported. No 1963 restored
state: ruin 1932-1999 (P3 fixed). Timeline: standing
1779-1930 with 1865 steam; damaged (partial) 1930-1932;
ruin 1932-1999; under_construction 1999-2002; rebuilt since.
Scenes: 6 plus today. See Stability for run-to-run
differences.

**water-tower** (Q2487636). Langs read: nl. Claims: 1932 built,
1986 tulips, 1987 conversion, 1991 new tulips all partly;
1990 storm unsupported (weak sources only, as designed). The
1986 tulips verify via nl.wikipedia (P2 fixed) and the film
is short, not too little (P1 outcome fixed). Timeline:
standing 1932-1986; tulips 1986-1987; converted 1987-1991;
new tulips since. Scenes: 4 plus today.

### Stability

De Adriaan ran four times clean (r3 plus s1-s3): full_film
every time (11 to 12 verified, 9 to 10 eras). The tower ran
three times clean (t1-t3) after a Wikidata outage window
failed s1-s3 (see P18): short_film every time (r3/t1 4
verified/4 eras, t2/t3 3/3). Era years match except s2, which
found a 1925 demolition-threat claim instead of 1920
electrification, and t2, which found 2013 reuse instead of
1987. Nothing else is identical: research rewords every claim
each run; verdicts flip supported/partly (de-adriaan 1779,
1802, 1865, 1920, 2002, 2003, 2004; tower 1991 partly in
r3/t1, unsupported in t2/t3 on near-identical wording); the
1865 scene flips standing/rebuilt 2-2; the 1930 storm is a
scene in r3/s1/s2 and a caption line in s3. Runs with 2002
partly (s1, s2) show it burnt (partial); runs with 2002
supported (r3, s3) show it rebuilt (P16). Ruin 1932-1999 and
no 1963 state held in all four De Adriaan runs. So P1 is
fixed at outcome level only; identical results need research
determinism plus P16.

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

### Found 27 October (Block 5, not fixed yet)

- P16. Partly claims blank their event before classification
  (`timeline_events`), so context words in the rewrite set a wrong
  condition while the description stays right: de-adriaan s1/s2
  show 2002 burnt (partial) "full windmill back on skyline" for
  the reopening ("70 years after fire"); kintai shows 1674 ruin
  "bridge re-erected"; rubjerg shows under_construction
  1899-1953; belem shows under_construction 1514-1845 and
  demolished 1845-1940 for a removed barracks. The completion
  flag already filters uncompleted claims, so completed partly
  claims should keep their event. Must fix before painting: the
  painter would paint fire in 2002.
- P19. Distance-only top-5 ranking cuts the true object when the
  geocoded point lands nearer something else: heidelberg keeps
  four castle parts and cuts the castle (11th) so vision
  honestly answers NONE; the colosseum run keeps the metro
  station (36 m) and cuts the amphitheatre, so vision picks the
  only "Colosseo" it is offered and the pipeline films the
  wrong object with full confidence. Rank needs quality
  signals (sitelinks, instance-of, name match), not distance
  alone.
- P20. Vision answers NONE though the right candidates are
  listed: vasa 3/3 with "Vasa Museum" and "Vasa" present for a
  photo of the ship. Diagnose against the photo; the pick prompt
  may need kinds or descriptions, not bare names.
- P17. Overpass is dead from this network: every identify burns
  60 to 90 s on timeouts and gets zero candidates, so Wikidata
  nearby is a single point of failure and the 15 s identify
  target misses everywhere. Shorten the Overpass timeout,
  stop blocking identify on it, or drop it while it is down.
- P18. Identify has no redundancy: one Wikidata error (HTTP 429
  or 5xx, no retry on transport errors in `mediawiki_get`)
  plus dead Overpass means "no named candidates" and
  not_identified. A 3-minute Wikidata window failed all three
  tower stability runs; de-adriaan and the re-runs around them
  were fine. Retry transport errors, and keep a failed source
  from emptying the candidate list when the other source
  already answered.
- P10 still open: the oak's 1026 comes from research wording
  ("800-1200 years old"), not Wikidata, so the precision rule
  does not catch it. Either the research prompt must refuse
  midpoint years for age ranges, or round claims must carry
  their range.
- P1 partly open: outcomes no longer flap (tower short, never
  too little), but research rewords claims every run and
  verdicts flip supported/partly, so scenes and states differ
  run to run (see Stability). Identical results need
  determinism at research level, or scene choice that is
  robust to rewording.

## New objects (27 October, nobody tuned for)

Six new objects, different countries, languages and types, no
war or politics subjects. Photos in `samples/` (table above),
logs `out/testset/*-new.log`. Result: 3 full films, 1 short
film, 2 not identified.

| Object | Outcome | Ident | Facts | Resrch | Fetch | Verify | Total |
|---|---|---|---|---|---|---|---|
| sagrada-familia | full (6v, 5e, 3g) | 73.3 | 0.2 | 35.3 | 128.6 | 79.6 | 317.1 |
| vasa-ship | not identified (vision NONE x3) | - | - | - | - | - | - |
| colosseum | full, wrong object (7v, 6e, 2g) | 95.4 | 0.3 | 36.0 | 100.3 | 56.1 | 288.1 |
| heidelberg-castle | not identified (true object cut) | - | - | - | - | - | - |
| belem-tower | short (4v, 4e, 4g) | 67.8 | 0.7 | 37.7 | 6.5 | 45.7 | 158.4 |
| atomium | full (8v, 5e, 5g) | 66.8 | 0.6 | 23.0 | 6.7 | 128.1 | 225.2 |

**sagrada-familia.** Langs read: ca, es, en (Catalan first).
Claims: 1882 start, 1883 Gaudi takeover, 1936 crypt fire and
vandalism, 1954 Passion facade, 2002 Glory facade and schools
move, 2026 Jesus tower; six spares unverified. Scenes: 1882
under_construction, 1883 rebuilt (an architect handover as a
physical state is generous), 1936 burnt (partial) crypt
interior (an interior as a scene; "crypt" escapes the
interior veto), 1954 standing, 2002 moved (the schools
pavilion, part scope). Fetch took 129 s: full Wikipedia
articles in three languages, read serially under the
one-at-a-time rule.

**vasa-ship.** Not identified, three attempts: candidates
included the Vasa Museum (8 m) and the ship Vasa (41 m) but
vision answered NONE every time (P20).

**colosseum.** Identified Q1229235 ("Colosseo", the metro
station) instead of Q10285 (the amphitheatre): the geocoded
point sits 36 m from the station item while the amphitheatre
falls outside the distance-only top 5, so vision was never
offered the right object (P19). The pipeline then produced a
confident full_film about metro Line B (1955 opening) and
Line C works: the worst failure mode, wrong but certain.

**heidelberg-castle.** Not identified, honestly: the geocoded
point lands amid castle parts (Ruprechtsbau, courtyard,
fountain hall, library), the castle itself ranks 11th and is
cut from the top 5, and vision correctly answers NONE (P19).

**belem-tower.** Langs read: pt, en. Claims: 1514 built
partly, 1580 surrender, 1655 plaque, 1845 barracks demolition,
1940 and 1997 restorations; short_film honestly earned.
Timeline shows P16 twice: under_construction 1514-1845 (331
years, from "construction started" in a blanked-event
rewrite) and demolished 1845-1940 for a removed barracks.

**atomium.** Langs read: nl, fr, en (Brussels trilingual,
correct). Claims: 1956 build, 1958 Expo, 2004-2006
renovation, 2005 lighting, 2006 pavilion. Timeline is five
clean standing segments; two descriptions leak Dutch
("De bouw van het Atomium begon", "renovatie in 2004"),
cosmetic only.

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

## Block E: afternoon fixes and re-run (27 October)

Blocks A to D plus post-batch fixes, all test-first (288 tests
green). Re-runs with the cache off: r5 targeted eight, r6 final
code six, christ r7, stability u1 to u3 for the tower and
De Adriaan, fresh f1 for six new untuned objects plus f2
retries, loc2 GPS-spot identifies for all 23 located photos.
Logs `out/testset/*.log` (git-ignored). Research and story
runs verify on Muse Spark Open with Meta fallback.

Wrong-object count: 0 filmed. Every research run either named
the depicted object or honestly answered not identified. One
label-level mismatch: hungarian f1 named the National
Assembly (the institution) while its sources answered thin;
the film content was still building history, and the f2 retry
named the Hungarian Parliament Building.

### Targeted re-runs (r6, final code)

| Object | Outcome | Ident | Facts | Resrch | Fetch | Verify | Total | Story | Budget |
|---|---|---|---|---|---|---|---|---|---|
| major-oak | full (7v, 7e, 4g) | 13.5 | 0.5 | 25.5 | 5.3 | 90.8 | 135.6 | 122 | met, miss |
| rubjerg-knude | full (11v, 9e, 5g) | 19.6 | 0.5 | 42.2 | 5.6 | 64.1 | 132.1 | 112 | miss, miss |
| heidelberg-castle | full (24v, 24e, 2g) | 25.3 | 0.6 | 67.4 | 3.8 | 100.7 | 197.9 | 172 | miss, miss |
| atomium | full (8v, 5e, 3g) | 14.1 | 0.5 | 30.9 | 3.5 | 64.3 | 113.2 | 99 | met, miss |
| christ-redeemer | not identified (vision NONE) | - | - | - | - | - | - | - | - |
| vasa-ship | not identified (honest NONE) | - | - | - | - | - | - | - | - |
| christ-redeemer r7 | full (13v, 9e, 6g) | 15.1 | 0.8 | 43.7 | 11.6 | 79.2 | 150.4 | 135 | near, miss |

Story is facts plus research plus fetch plus verify. Fetch is
fixed for good: heidelberg 562 s in r4 is 3.8 s here
(extracts fail fast at 30 s with 2 tries, no refetch across
phases, reference tails trimmed, 8 plain workers). Verify now
dominates every story (64 to 101 s): best of three over a
reasoning model. Identify meets 15 s on atomium and the oak;
heidelberg (25.3 s, two vision rounds) and rubjerg (19.6 s)
miss on vision plus the second look, not on sources.

**major-oak.** P10 closed: scenes read "about 800 to 1,200
years old", including the surroundings scenes. No legend
verified.

**rubjerg-knude.** P23 closed: the only moved segment is the
genuine 2019 relocation; the moved exhibition is a caption.

**heidelberg-castle.** 24 verified claims, full film. The r5
failure was a transient all-sources-empty window; r6
identified first try.

**atomium.** The r5 failure was a geocoding namesake: Nominatim
top-1 flipped between the monument and a pharmacy called
Atomium a kilometre away. Geocode now takes five hits and
keeps the most important, and typed-place starts search
1 km (GPS stays 250 m). Fixed and full film.

**christ-redeemer.** The r5 film named the mountain: vision
picked the statue correctly, then the second look vetoed it
with a hallucinated "Cristo Rei in Almada". Fixes: candidates
carry real instance-of kinds from P31 (not "wikidata item"),
both vision prompts name where the photo was taken and the
look is grounded with the distance, and a veto needs two NOs.
r7 is a full statue film (13 verified, lightning damage and
restorations). The look still flaps to honest NONE on some
runs; never to the wrong object.

**vasa-ship.** Honest NONE, correctly: the photo shows a diver
diorama inside the museum, EXIF GPS is a North Pole
placeholder, and no candidate is depicted. New rule: when the
GPS run matches nothing and a place was given, one retry runs
from the place, still gated by the vision pick. The retry
prompt bars settling for containers.

### Fresh six (f1, nobody tuned for)

5 full films and 1 short on first runs; both retries full.

| Object | Outcome | Ident | Facts | Resrch | Fetch | Verify | Total | Story | Budget |
|---|---|---|---|---|---|---|---|---|---|
| mont-saint-michel | full (29v, 28e, 7g) | 15.9 | 0.7 | 37.0 | 6.6 | 91.7 | 151.9 | 136 | near, miss |
| neuschwanstein f2 | full (14v, 11e, 7g) | 17.0 | 0.6 | 36.9 | 11.9 | 77.6 | 144.0 | 127 | miss, miss |
| sultan-ahmed-mosque | full (5v, 5e, 3g) | 14.7 | 0.5 | 30.8 | 6.2 | 39.3 | 91.5 | 76 | met, miss |
| borobudur | full (17v, 15e, 3g) | 14.3 | 0.6 | 51.4 | 1.8 | 63.1 | 131.4 | 117 | met, miss |
| hallgrimskirkja | full (6v, 5e, 7g) | 21.2 | 0.6 | 31.7 | 11.4 | 44.2 | 109.2 | 88 | miss, miss |
| hungarian-parliament f2 | full (6v, 6e, 6g) | 16.8 | 0.5 | 41.5 | 5.6 | 52.7 | 117.1 | 100 | near, miss |

Cited wiki languages: mont fr and en, neuschwanstein de and
en, the rest en only. Neuschwanstein f1 hit a transient
empty-candidate window; f2 full. Hungarian f1 named the
institution on thin sources (short, content still building
history); f2 named the building (full).

**mont-saint-michel.** Photo is the abbey tower close up;
abbey picked correctly. Timeline runs 708 to 2001 with
sensible states (sacks, collapses, rebuilds, the 1834
workshop fire as burnt partial). The implausible-span flag
fired live on the 28-year burnt span: held for review, never
painted silently.

**neuschwanstein.** Langs de, en. Full film, no state
surprises.

**sultan-ahmed-mosque.** The 1912 outbuilding fire classified
burnt for the whole mosque; fixed the same evening (P25):
outlying, ancillary and surrounding structures are
caption-only, like other surroundings.

**borobudur.** Two same-evening fixes (P25): a ruler moving a
capital ("King Mpu Sindok moved the Mataram capital") no
longer moves the temple, and taken artefacts ("eight
cartloads of sculptures") no longer move it either, while a
statue moved to a museum square and Queen Mary keep genuine
moves. The temple burial itself stays a caption until claim
splitting exists; never a state either way.

**hallgrimskirkja.** 1937 commission to the 1986 nave
completion, clean standing and under_construction segments.

**hungarian-parliament.** P24: occupants moving never move
the building ("the National Assembly has met in the
Building" is a caption). War claims (1945 bombings, 1956)
stayed unsupported and unfilmed, as the rule requires.

### Photographer-position identifies (loc2, final code)

23 located photos (EXIF spots 50 to 250 m from the object,
often nearer something else), identify with no typed place:
20 correct, 3 honest failures, 0 wrong. Eiffel (was Rives de
la Seine) and Djenné (was Old Towns) now pick correctly;
colosseum picks the amphitheatre 3/3 with no rejections.
Christ answers NONE from its GPS spot (no place grounding
there); rubjerg hit a transient empty window; vasa rejects
every pick for its diorama photo. The fresh six score 6/6
from spots 53 to 228 m away, including a restaurant, a
museum and an office closer to the spot than the object.

### Stability on the new metric

Metric: outcome, eras with conditions and scene years
identical across three cache-off runs; wording may differ.
Result: UNSTABLE on both objects, and honestly so.

Tower u1 to u3: all short_film, all standing, but the eras
differ (1932/1986/2023 vs 1932/1986/1991 vs 1986/1991):
the 1932 build claim voted partly then unsupported on
different wordings, the 1991 tulip claim flipped the other
way, and research reported the conversion as 2023 once and
2026 once. De Adriaan u1 to u3: all full_film with the same
skeleton (1779 standing, 1930 damaged, 1932 ruin, 2002
rebuilt) but middle scenes differ (1920 and 1802 come and
go; 1999 reads under_construction only when its claim lands
supported rather than partly).

Two variance sources, both model-side: research reports
different claim sets and wordings per run, and verify
verdicts flap on reworded claims (a quoted partly minority
loses 2-1 to unsupported). Scene choice given the claims is
deterministic, and the per-object cache (7-day refresh)
means a second visit shows the same film. Every run's film
is correct; the flap is which true scenes, never false
states. Follow-up, not tonight: weigh a quoting
confrontation round above quoteless majority votes, and
split compound claims into atomic ones.

### Timings against the budget

Identify within 15 s: met on 4 of 13 story runs (atomium,
oak, borobudur, sultan), near (15 to 17 s) on 4 more;
vision plus the second look dominate, Overpass sits inside
its 5 s budget. Story within 60 s of confirming: missed on
all 13 (76 to 172 s); verify 39 to 115 s plus research 26
to 67 s. Block C's 9-of-12 story target is missed: the
story needs fewer or cheaper verify rounds, not faster
fetch. Fetch met its budget everywhere (0.5 to 12 s).

### P-number status

Fixed: P10 (ranges end to end, surroundings scenes read the
range), P16 (partly keeps its event), P17 (Overpass
optional on 5 s), P19 (quality ranking; heidelberg,
colosseum, atomium live), P22 (fetch fail fast, no
refetch, trimmed tails, 8 workers), P23 (moved contents),
P24 (moved occupants and organisations, new), P25 (ruler
moves, taken artefacts, outlying structures, new).
Partly open: P18 (retries plus wpgeo redundancy landed,
but transient all-empty windows persist, including a
Wikidata geosearch outage returning zero for Rome), P20
(kinds, descriptions, grounded looks, two-NO veto; christ
still flaps to honest NONE), P1 (stability metric as
above). Open: P11 (quote preference), P13, P14, plus the
crown/regalia contents edge and claim splitting for
burials. Painting blockers: none that silently mistates;
the open items cost scenes or retries, not false eras.
