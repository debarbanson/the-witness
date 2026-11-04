"""Step 7: build a live film page. Every frame is a pure function of t."""

import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from witness import children, states
from witness.research import CONSTRUCTION_EVENTS
from witness.verify import filmed, normalise_text

TITLE_S = 3
ANCHOR_S = 2
ERA_S = 7
TODAY_S = 5
END_S = 6


def filmable(scene, claims, audience="adult") -> bool:
    """A scene reaches the film only with a written sentence pinned
    to immutable evidence (claim, URL, quote) that still matches a
    supported kept claim. Anything else is refused; there is no
    filler line. The children's film also needs the children's
    sentence; it never borrows the adult one."""
    return refusal_reason(scene, claims, audience=audience) is None


def refusal_reason(scene, claims, audience="adult") -> str | None:
    """Why a scene cannot reach the film, or None when it can. A
    caption whose claim changed or lost support is invalidated."""
    stored = scene.get("caption_sentence") or {}
    if not stored.get("text") or stored.get("claim_year") is None:
        return "no written sentence from its own claim"
    if stored.get("claim_year") != scene.get("from_year"):
        return "its caption cites another year's claim"
    evidence = stored.get("evidence") or {}
    if not evidence.get("claim") or not evidence.get("url") or not evidence.get("quote"):
        return "no evidence reference"
    same_page = [claim for claim in claims
                 if claim.get("year") == stored.get("claim_year")
                 and claim.get("url") == evidence["url"]]
    if not same_page:
        return "its claim is gone from the research"
    matched = [claim for claim in same_page
               if claim.get("claim") == evidence["claim"]]
    if not matched:
        return "its claim changed since the caption was written"
    if not any(filmed(claim) for claim in matched):
        return "its claim is no longer supported"
    if audience == "child" and not (stored.get("child") or {}).get("text"):
        return "no children's sentence"
    return None


_STAMP_MONTHS = ("january", "february", "march", "april", "may",
                  "june", "july", "august", "september", "october",
                  "november", "december")


_FULL_DATE_RES = (r"(\d{1,2})\s+([A-Za-z]+),?\s*(\d{4})",
                  r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})")


def _norm_date(text) -> str:
    """Date words compared loosely: case, ordinals and punctuation go,
    so 'April 23, 1932' meets '23 April 1932'. Anything else must
    match word for word."""
    lowered = (text or "").lower()
    lowered = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", lowered)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def _full_date_parts(label):
    """(day, month, year) when the label is just one full date, else
    None. A label with extra words is a description, not a date."""
    found = re.search(_FULL_DATE_RES[0], label or "")
    if found:
        day, month, date_year = found.groups()
    else:
        found = re.search(_FULL_DATE_RES[1], label or "")
        if not found:
            return None
        month, day, date_year = found.groups()
    if month.lower() not in _STAMP_MONTHS:
        return None
    want = {_norm_date(f"{int(day)} {month} {date_year}"),
            _norm_date(f"{month} {int(day)} {date_year}")}
    if _norm_date(label) not in want:
        return None
    return int(day), month, date_year


_STAMP_QUALIFIERS = frozenset({"around", "about", "circa", "c",
                               "approximately", "approx"})


def _span_in(text, span) -> bool:
    """A normalized span with token boundaries on both sides, so '1
    april 1900' never matches inside '11 april 1900'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(span) + r"(?![a-z0-9])",
                     text or "") is not None


def stamp_for(label, year, quote) -> str:
    """The shown stamp: the full date only when the label is just a
    date and that exact date (day, month and year together, either
    order) appears in the bound quote; a supported qualifier with
    its year when the quote carries that span; otherwise the year
    alone."""
    if (label or "").strip() == str(year):
        return str(year)
    parts = _full_date_parts(label)
    norm_quote = _norm_date(quote)
    if parts is None:
        words = _norm_date(label).split(" ")
        if (len(words) == 2 and words[0] in _STAMP_QUALIFIERS
                and words[1] == str(year)
                and _span_in(norm_quote, f"{words[0]} {year}")):
            return label.strip()
        return str(year)
    day, month, date_year = parts
    forms = {_norm_date(f"{day} {month} {date_year}"),
             _norm_date(f"{month} {day} {date_year}")}
    if any(_span_in(norm_quote, form) for form in forms):
        return label.strip()
    return str(year)


def caption_for(scene, audience="adult"):
    """A date stamp plus one sentence: the written sentence for the
    scene, or nothing. Never cut, never borrowed."""
    stored = scene.get("caption_sentence") or {}
    quote = (stored.get("evidence") or {}).get("quote", "")
    stamp = stamp_for(scene.get("date_label"), scene.get("from_year"), quote)
    if audience == "child":
        return (stamp, (stored.get("child") or {}).get("text", ""))
    return (stamp, stored.get("text", ""))


def source_site(url) -> str:
    """Short on-screen source name for a URL."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host.endswith("wikipedia.org"):
        return "Wikipedia"
    if host.endswith("wikidata.org"):
        return "Wikidata"
    return host


def source_title(url) -> str:
    """Readable page title for a source URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("title"):
        return query["title"][0].replace("_", " ")
    path = unquote(parsed.path).strip("/")
    if "/" in path:
        path = path.rsplit("/", 1)[-1]
    title = path.replace("_", " ").replace("-", " ").strip()
    if title:
        return title
    return parsed.netloc.lower().removeprefix("www.")


def end_sources(scenes, claims, cache=None, more=()) -> list:
    """Unique sources behind the filmed scenes: the cited claims of
    filmable scenes plus their caption lines, then the pages of the
    more checked facts the end card lists. URL kept for the web
    page, site plus title for the film end card. Provenance comes
    from the stored evidence bundle, so the end card survives cache
    expiry. A claim neither a filmed scene nor the end card cites is
    never listed."""
    urls = []
    for scene in scenes:
        if not filmable(scene, claims):
            continue
        stored = scene.get("caption_sentence") or {}
        evidence = stored.get("evidence") or {}
        for url in (stored.get("claim_url"), evidence.get("url"),
                    evidence.get("sentence_url")):
            if url and url not in urls:
                urls.append(url)
        for line in scene.get("caption_lines", []):
            entry = children.claim_for_line(
                claims, line.get("year"), line.get("url"))
            if entry and entry.get("url") and entry["url"] not in urls:
                urls.append(entry["url"])
    for fact in more:
        if fact.get("url") and fact["url"] not in urls:
            urls.append(fact["url"])
    return [{"url": url, "site": source_site(url),
             "title": end_title(url, cache)} for url in urls]


MORE_MAX = 6


def display_claim(text) -> str:
    """A claim for a facts list: the stored text starts with
    "label (date): ", which would double the year the item already
    shows. Drop that prefix for display only, and only when text
    remains; stored claims, evidence and films keep it."""
    cut = re.sub(r"^[^:()]*\([^)]*\d[^)]*\):\s*", "", text or "", count=1)
    return cut if cut else (text or "")


def film_fact(stamp, stored) -> dict | None:
    """The checked claim behind one filmed caption, as the end card
    lists it after the film: the caption's stamp, the claim in plain
    words and its page. None without a claim or a page."""
    evidence = stored.get("evidence") or {}
    url = evidence.get("url") or stored.get("claim_url")
    text = display_claim(evidence.get("claim", "")).strip()
    if not text or not url:
        return None
    return {"stamp": stamp, "text": text[0].upper() + text[1:],
            "site": source_site(url), "url": url}


def more_facts(scenes, claims, images=None, audience="adult") -> list:
    """The checked facts the film does not show, for the list after
    the film: supported, unrefused claims with a year and a page, in
    year order, each fact once, at most MORE_MAX. A claim counts as
    shown when a filmed scene's caption cites it; with `images` only
    painted scenes count, so a fact whose painting was dropped still
    gets listed. The text is the checked claim itself, never a model
    rewrite; only the display prefix goes and the first letter is
    raised. The children's film lists none: these are adult texts."""
    if audience != "adult":
        return []
    shown = set()
    for scene in dated(scenes):
        if images is not None and str(scene["from_year"]) not in images:
            continue
        if not filmable(scene, claims, audience):
            continue
        stored = scene.get("caption_sentence") or {}
        evidence = stored.get("evidence") or {}
        shown.add((stored.get("claim_year"), evidence.get("url"),
                   evidence.get("claim")))
    facts, seen = [], set()
    candidates = [claim for claim in claims
                  if filmed(claim) and isinstance(claim.get("year"), int)
                  and claim.get("url")]
    for claim in sorted(candidates, key=lambda claim: claim["year"]):
        if (claim["year"], claim["url"], claim.get("claim")) in shown:
            continue
        text = display_claim(claim.get("claim", "")).strip()
        if not text:
            continue
        text = text[0].upper() + text[1:]
        stamp = stamp_for(claim.get("date_text") or str(claim["year"]),
                          claim["year"], claim.get("quote", ""))
        if (stamp, text) in seen:
            continue
        seen.add((stamp, text))
        facts.append({"stamp": stamp, "text": text,
                      "site": source_site(claim["url"]),
                      "url": claim["url"]})
        if len(facts) == MORE_MAX:
            break
    return facts


def end_title(url, cache=None) -> str:
    """The page's real title when fetched, else the URL slug.

    Wikipedia titles always come from the URL: the article name beats
    the browser tab ("De Adriaan, Haarlem", not "... - Wikipedia").
    """
    if cache is not None and source_site(url) != "Wikipedia":
        title = cache.get(f"{url}#title")
        if title:
            return title
    return source_title(url)


def today_card(photo_year, own_photo, last_scene, claims=()) -> tuple:
    """The closing card names the photo's year and claims nothing about
    today. Unknown year: just "Your photo"."""
    del own_photo, last_scene, claims
    if isinstance(photo_year, int):
        return (f"Photographed in {photo_year}.", "")
    return ("Your photo.", "")


def scene_site(scene, claims=()) -> str:
    """On-screen source for one scene: the caption's own evidence
    URL, the page whose sentence supported the caption."""
    del claims
    evidence = (scene.get("caption_sentence") or {}).get("evidence") or {}
    url = evidence.get("sentence_url") or evidence.get("url")
    return source_site(url) if url else ""


ORIGIN_EVENTS = CONSTRUCTION_EVENTS | {"opened", "founded", "planted"}

# The card's 840 px line breaks this after "first", never before a
# lone "date:": the no-break space keeps "checked date:" together.
FIRST_CHECKED = "My first checked date:"


def starts_story(scene, claims) -> bool:
    """True only when the fact the scene's caption cites is the object's
    beginning: a build, opening, founding or planting, or Wikidata's
    build date. A restoration or a fire is never where a story starts."""
    stored = scene.get("caption_sentence") or {}
    evidence = stored.get("evidence") or {}
    if not evidence.get("claim"):
        return False
    return any(claim.get("year") == stored.get("claim_year")
               and claim.get("url") == evidence.get("url")
               and claim.get("claim") == evidence["claim"]
               and (claim.get("anchor") == "build"
                    or (claim.get("event") or "").lower() in ORIGIN_EVENTS)
               for claim in claims)


def anchor_card(first_scene, claims=()) -> dict:
    """The opening card: a neutral line plus one year, or the age
    range. A from_year the scene's own label does not carry is a
    computed sort key, never shown; the human label speaks instead.
    Only a beginning (starts_story) says the story starts there; any
    other first fact is named as the first checked date."""
    label = first_scene.get("date_label", "") or ""
    if states.is_age_range(label):
        words = label[:-4] if label.endswith(" old") else label
        return {"line": "My story starts", "label": f"{words} ago."}
    start = starts_story(first_scene, claims)
    year = first_scene.get("from_year")
    if isinstance(year, int) and str(year) in label:
        evidence = ((first_scene.get("caption_sentence") or {})
                    .get("evidence") or {})
        shown = stamp_for(label, year, evidence.get("quote", ""))
        return {"line": "My story starts in" if start else FIRST_CHECKED,
                "label": f"{shown}."}
    return {"line": "My story starts" if start else FIRST_CHECKED,
            "label": label or "before living memory"}


def dated(scenes) -> list:
    """Scenes with a filmable year: ints, never age ranges."""
    return [s for s in scenes if isinstance(s.get("from_year"), int)
            and not states.is_age_range(s.get("date_label", ""))]


def build_timeline(scenes, images, claims, audience="adult") -> list:
    """Contiguous segments: title, anchor, one era per painting, today,
    end. Empty when no era is filmable: that is a facts-only result,
    never a title-and-today film."""
    eras = [s for s in dated(scenes)
            if str(s["from_year"]) in images and filmable(s, claims, audience)]
    if not eras:
        return []
    plan = [{"kind": "title", "start": 0, "end": TITLE_S}]
    plan.append({"kind": "anchor", "start": TITLE_S, "end": TITLE_S + ANCHOR_S})
    t = TITLE_S + ANCHOR_S
    for position, scene in enumerate(eras):
        year = scene["from_year"]
        stamp, sentence = caption_for(scene, audience)
        plan.append({"kind": "era", "year": year,
                     "date_label": scene.get("date_label", str(year)),
                     "image": images[str(year)], "start": t, "end": t + ERA_S,
                     "caption": [stamp, sentence],
                     "site": scene_site(scene, claims)})
        t += ERA_S
    plan.append({"kind": "today", "start": t, "end": t + TODAY_S})
    plan.append({"kind": "end", "start": t + TODAY_S,
                 "end": t + TODAY_S + END_S})
    return plan


def served_era_name(key, src) -> str:
    """The served filename follows the bytes, not the stored name:
    paintings ship byte-identical in their original format, so the
    model's provenance signal survives."""
    try:
        magic = Path(src).read_bytes()[:12]
    except OSError as exc:
        raise ValueError(f"cannot serve {key}: {exc}") from exc
    if magic.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif magic.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif magic.startswith(b"RIFF") and magic[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise ValueError(f"cannot serve {key}: unknown image format")
    return f"era_{key}.{ext}"


def write_film(out_dir, research, images, photo, photo_credit,
               era_files=None, photo_file=None,
               cutout_file=None, photo_year=None, own_photo=False, cache=None,
               folder="film", audience="adult", sibling=None, spot=None,
               photo_source=None):
    """film.json plus film.html plus copied assets under out_dir/film/.

    Paintings ship byte-identical in their original format, so the
    model's provenance signal survives; the visible AI label stays.
    Built in a fresh staging folder, then published over film/ in
    one swap, so a re-render never leaves a stale asset behind and a
    failed one keeps the last good film. The children's film is a
    second complete folder (folder="film/child") linked both ways
    through the sibling field, which the player turns into its
    Adults/Children switch."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="film.staging-", dir=out_dir))
    try:
        _build_film(staging, research, images, photo, photo_credit,
                    era_files=era_files,
                    photo_file=photo_file, cutout_file=cutout_file,
                    photo_year=photo_year, own_photo=own_photo, cache=cache,
                    audience=audience, sibling=sibling, spot=spot,
                    photo_source=photo_source)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    final = out_dir / folder
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        aside = final.parent / (final.name + ".retired")
        if aside.exists():
            shutil.rmtree(aside, ignore_errors=True)
        final.rename(aside)
        try:
            staging.rename(final)
        except BaseException:
            aside.rename(final)
            raise
        shutil.rmtree(aside, ignore_errors=True)
    else:
        staging.rename(final)
    return final


def _build_film(film_dir, research, images, photo, photo_credit,
                era_files=None, photo_file=None,
                cutout_file=None, photo_year=None, own_photo=False,
                cache=None, audience="adult", sibling=None, spot=None,
                photo_source=None):
    """Write one complete film folder; write_film publishes it."""
    name = research["object"]["name"]
    claims = research.get("claims", [])
    scenes = dated(research.get("scenes", []))
    plan = build_timeline(research.get("scenes", []), images, claims,
                          audience=audience)
    if not plan:
        raise ValueError("no filmable eras; facts only")
    film_scenes = []
    in_film = []
    for scene in scenes:
        key = str(scene["from_year"])
        if key not in images or not filmable(scene, claims, audience):
            continue
        stamp, sentence = caption_for(scene, audience)
        stored = scene.get("caption_sentence") or {}
        fact = film_fact(stamp, stored) if audience == "adult" else None
        if fact is not None and fact not in in_film:
            in_film.append(fact)
        cited = None
        if stored.get("text") and stored.get("claim_year") is not None:
            cited = {"year": stored.get("claim_year"),
                     "url": stored.get("claim_url")}
        film_scenes.append({"year": scene["from_year"],
                            "date_label": scene.get("date_label", key),
                            "image": images[key],
                            "caption": [stamp, sentence],
                            "site": scene_site(scene, claims),
                            "caption_claim": cited})
    attribution = []
    if research.get("timings", {}).get("identify_steps", {}).get("overpass_s") is not None:
        attribution.append("© OpenStreetMap contributors")
    painted = [s for s in scenes
               if str(s["from_year"]) in images
               and filmable(s, claims, audience)]
    last = painted[-1] if painted else {"from_year": "today", "state": {}}
    today_line, today_sub = today_card(photo_year, own_photo, last, claims)
    # The opening card starts at the first filmed scene: painted
    # scenes passed the filmable gate, so the card carries the same
    # acceptance and binding as every scene. An unaccepted age claim
    # never opens the film.
    first = painted[0] if painted else {}
    more = more_facts(research.get("scenes", []), claims, images,
                      audience=audience)
    film = {"object": name, "kind": research["object"].get("kind", ""),
            "photo": photo, "photo_credit": photo_credit,
            "photo_source": photo_source,
            "cutout": ("cutout.png" if cutout_file is not None else None),
            "today_line": today_line, "today_sub": today_sub,
            "anchor": anchor_card(first, claims),
            "attribution": attribution,
            "ai_label": "Painted scenes are AI imagery, checked against verified sources.",
            "sources": end_sources(research.get("scenes", []),
                                   research.get("claims", []), cache,
                                   more=more),
            "film_facts": in_film,
            "more_facts": more,
            "segments": plan, "scenes": film_scenes,
            "audience": audience, "sibling": sibling,
            "sibling_page": (sibling[:-len("film.json")] + "film.html"
                             if sibling and sibling.endswith("film.json")
                             else None),
            "spot": "spot.html" if spot is not None else None}
    (film_dir / "film.json").write_text(json.dumps(film, indent=1))
    template = (Path(__file__).parent / "film.html").read_text()
    embedded = json.dumps(film).replace("</", "<\\/")
    tag = ('<script id="film-data" type="application/json">'
           "__FILM_JSON__</script>")
    assert tag in template
    (film_dir / "film.html").write_text(
        template.replace(tag, tag.replace("__FILM_JSON__", embedded)))
    if photo_file is not None:
        shutil.copy(photo_file, film_dir / "today.jpg")
    for key, src in (era_files or {}).items():
        if src is not None:
            shutil.copy(src, film_dir / images[key])
    if cutout_file is not None:
        shutil.copy(cutout_file, film_dir / "cutout.png")
    if spot is not None:
        (film_dir / "spot.json").write_text(json.dumps(spot, indent=1))
        template = (Path(__file__).parent / "spot.html").read_text()
        embedded = json.dumps(spot).replace("</", "<\\/")
        tag = ('<script id="spot-data" type="application/json">'
               "__SPOT_JSON__</script>")
        assert tag in template
        (film_dir / "spot.html").write_text(
            template.replace(tag, tag.replace("__SPOT_JSON__", embedded)))
    return film_dir
