"""Step 7: build a live film page. Every frame is a pure function of t."""

import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from witness import states
from witness.verify import normalise_text

TITLE_S = 3
ANCHOR_S = 2
ERA_S = 7
TODAY_S = 5
END_S = 6


def filmable(scene, claims) -> bool:
    """A scene reaches the film only with a written sentence pinned
    to immutable evidence (claim, URL, quote) that still matches a
    supported kept claim. Anything else is refused; there is no
    filler line."""
    return refusal_reason(scene, claims) is None


def refusal_reason(scene, claims) -> str | None:
    """Why a scene cannot reach the film, or None when it can. A
    caption whose claim changed or lost support is invalidated."""
    stored = scene.get("caption_sentence") or {}
    if not stored.get("text") or stored.get("claim_year") is None:
        return "no written sentence from its own claim"
    evidence = stored.get("evidence") or {}
    if not evidence.get("claim") or not evidence.get("url") or not evidence.get("quote"):
        return "no evidence reference"
    for claim in claims:
        if (claim.get("year") == stored.get("claim_year")
                and claim.get("url") == evidence["url"]):
            if claim.get("verdict") != "supported":
                return "its claim is no longer supported"
            if claim.get("quote") != evidence["quote"]:
                return "its claim changed since the caption was written"
            return None
    return "its claim is gone from the research"


def caption_for(scene):
    """A date stamp plus one sentence: the written sentence for the
    scene, or nothing. Never cut, never borrowed."""
    stamp = scene.get("date_label") or str(scene.get("from_year"))
    stored = (scene.get("caption_sentence") or {}).get("text", "")
    return (stamp, stored)


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


def end_sources(claims, cache=None) -> list:
    """Unique sources behind the verified claims: URL kept for the web
    page, site plus title for the film end card. A URL reaches the end
    card only when it was really fetched (it is in the cache) and its
    quote appears literally in the fetched text."""
    seen = []
    entries = []
    for claim in claims:
        url = claim.get("url")
        if not url or url in seen:
            continue
        if claim.get("verdict") != "supported":
            continue
        if not _provenanced(claim.get("quote") or "", url, cache):
            continue
        seen.append(url)
        entries.append({"url": url, "site": source_site(url),
                        "title": end_title(url, cache)})
    return entries


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


def _provenanced(quote, url, cache) -> bool:
    if cache is None:
        return False
    text = cache.get(url)
    if not text:
        return False
    norm = normalise_text(quote)
    return len(norm) >= 30 and norm in normalise_text(text)


DEATH_EVENTS = frozenset({"died", "dead", "demolished", "destroyed"})


def last_claim_event(last_scene, claims) -> str:
    """The event behind the last scene's caption, if it cites one."""
    cited = last_scene.get("caption_sentence") or {}
    if not cited.get("text"):
        return ""
    for claim in claims:
        if (claim.get("year") == cited.get("claim_year")
                and claim.get("url") == cited.get("claim_url")):
            return (claim.get("event") or "").lower()
    return ""


def today_card(photo_year, own_photo, last_scene, claims=()) -> tuple:
    """The today caption agrees with the last verified state: a stale
    stock photo is dated, and a dead or gone object never claims to
    stand. The last scene's line is never repeated: with a photo note
    the note speaks alone, otherwise a past-tense line does."""
    year = last_scene.get("from_year")
    condition = (last_scene.get("state") or {}).get("condition", "standing")
    gone = (condition == "demolished"
            or last_claim_event(last_scene, claims) in DEATH_EVENTS)
    sub = ""
    if (not own_photo and isinstance(photo_year, int)
            and isinstance(year, int) and photo_year < year):
        sub = f"Photographed in {photo_year}."
    if gone:
        return (("", sub) if sub else ("And here I stood.", ""))
    return ("And here I stand today.", sub)


def scene_site(scene, claims=()) -> str:
    """On-screen source for one scene: its caption lines first, then
    the verified claims of its year, so every scene names a source."""
    for line in scene.get("caption_lines", []):
        if line.get("url"):
            return source_site(line["url"])
    for claim in claims:
        if (claim.get("year") == scene.get("from_year")
                and claim.get("url")
                and claim.get("verdict") == "supported"):
            return source_site(claim["url"])
    return ""


def anchor_card(first_scene) -> dict:
    """The opening card: one year, or "for" plus the age range."""
    label = first_scene.get("date_label", "") or ""
    if states.is_age_range(label):
        words = label[:-4] if label.endswith(" old") else label
        return {"line": "I have stood here for", "label": words}
    return {"line": "I have stood here since",
            "label": str(first_scene.get("from_year"))}


def dated(scenes) -> list:
    """Scenes with a filmable year: ints, never age ranges."""
    return [s for s in scenes if isinstance(s.get("from_year"), int)
            and not states.is_age_range(s.get("date_label", ""))]


def kept_layers(layers_root, era_files) -> dict:
    """Layer files per year, skipping dirs whose source.json does not
    name the kept painting: stale cut-outs never reach the film."""
    import hashlib

    kept = {}
    for year_dir in sorted(Path(layers_root).iterdir()):
        found = sorted(year_dir.glob("figure_*.png"))
        if not found:
            continue
        painting = era_files.get(year_dir.name)
        if painting is None:
            continue
        try:
            source = json.loads((year_dir / "source.json").read_text())
        except (OSError, ValueError):
            continue
        digest = hashlib.sha256(Path(painting).read_bytes()).hexdigest()
        if source.get("sha256") != digest:
            continue
        kept[year_dir.name] = [str(p) for p in found]
    return kept


def build_timeline(scenes, images, claims) -> list:
    """Contiguous segments: title, anchor, one era per painting, today, end."""
    plan = [{"kind": "title", "start": 0, "end": TITLE_S}]
    plan.append({"kind": "anchor", "start": TITLE_S, "end": TITLE_S + ANCHOR_S})
    eras = [s for s in dated(scenes)
            if str(s["from_year"]) in images and filmable(s, claims)]
    t = TITLE_S + ANCHOR_S
    for position, scene in enumerate(eras):
        year = scene["from_year"]
        stamp, sentence = caption_for(scene)
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


def save_jpeg(src, dest, quality=88) -> None:
    """A painting as a web-sized JPEG."""
    from PIL import Image

    Image.open(src).convert("RGB").save(dest, "JPEG", quality=quality)


def write_film(out_dir, research, images, photo, photo_credit, layers,
               era_files=None, layer_files=None, photo_file=None,
               cutout_file=None, photo_year=None, own_photo=False, cache=None):
    """film.json plus film.html plus copied assets under out_dir/film/.

    Paintings are served as JPEG; layers and the cut-out stay PNG for
    their transparency. Built in a fresh staging folder, then
    published over film/ in one swap, so a re-render never leaves a
    stale asset behind and a failed one keeps the last good film."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="film.staging-", dir=out_dir))
    try:
        _build_film(staging, research, images, photo, photo_credit, layers,
                    era_files=era_files, layer_files=layer_files,
                    photo_file=photo_file, cutout_file=cutout_file,
                    photo_year=photo_year, own_photo=own_photo, cache=cache)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    final = out_dir / "film"
    if final.exists():
        aside = out_dir / "film.retired"
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


def _build_film(film_dir, research, images, photo, photo_credit, layers,
                era_files=None, layer_files=None, photo_file=None,
                cutout_file=None, photo_year=None, own_photo=False,
                cache=None):
    """Write one complete film folder; write_film publishes it."""
    name = research["object"]["name"]
    claims = research.get("claims", [])
    scenes = dated(research.get("scenes", []))
    plan = build_timeline(research.get("scenes", []), images, claims)
    painted = {e["year"]: e["t"] for e in research.get("stream", [])
               if e["event"] == "scene_painted" and e.get("verdict") == "matches"}
    film_scenes = []
    for scene in scenes:
        key = str(scene["from_year"])
        if key not in images or not filmable(scene, claims):
            continue
        stamp, sentence = caption_for(scene)
        stored = scene.get("caption_sentence") or {}
        cited = None
        if stored.get("text") and stored.get("claim_year") is not None:
            cited = {"year": stored.get("claim_year"),
                     "url": stored.get("claim_url")}
        film_scenes.append({"year": scene["from_year"],
                            "date_label": scene.get("date_label", key),
                            "image": images[key],
                            "caption": [stamp, sentence],
                            "site": scene_site(scene, claims),
                            "caption_claim": cited,
                            "layers": (layers or {}).get(key, []),
                            "ready_at": painted.get(scene["from_year"], 0)})
    attribution = []
    if research.get("timings", {}).get("identify_steps", {}).get("overpass_s") is not None:
        attribution.append("© OpenStreetMap contributors")
    painted = [s for s in scenes
               if str(s["from_year"]) in images and filmable(s, claims)]
    last = painted[-1] if painted else {"from_year": "today", "state": {}}
    today_line, today_sub = today_card(photo_year, own_photo, last, claims)
    first = (research.get("scenes", []) or [{}])[0]
    film = {"object": name, "kind": research["object"].get("kind", ""),
            "photo": photo, "photo_credit": photo_credit,
            "cutout": ("cutout.png" if cutout_file is not None else None),
            "today_line": today_line, "today_sub": today_sub,
            "anchor": anchor_card(first),
            "attribution": attribution,
            "ai_label": "Painted scenes are AI imagery, checked against verified sources.",
            "sources": end_sources(research.get("claims", []), cache),
            "segments": plan, "scenes": film_scenes}
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
            save_jpeg(src, film_dir / f"era_{key}.jpg")
    for key, files in (layer_files or {}).items():
        layer_dir = film_dir / f"layers_{key}"
        layer_dir.mkdir(exist_ok=True)
        for i, src in enumerate(files):
            shutil.copy(src, layer_dir / f"figure_{i}.png")
    if cutout_file is not None:
        shutil.copy(cutout_file, film_dir / "cutout.png")
    return film_dir
