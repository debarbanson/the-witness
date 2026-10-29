"""Step 7: build a live film page. Every frame is a pure function of t."""

import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from witness import captions

TITLE_S = 3
ANCHOR_S = 2
ERA_S = 7
TODAY_S = 5
END_S = 6


def caption_for(scene, is_first=False):
    """First-person caption: the written sentence for the scene, or a
    plain line with no fact. Never cut, never borrowed."""
    year = scene["from_year"]
    condition = (scene.get("state") or {}).get("condition", "standing")
    first = _first_person(condition, year, is_first)
    stored = (scene.get("caption_sentence") or {}).get("text", "")
    if stored:
        return (first, stored)
    return (first, captions.fallback_line(scene))


def _first_person(condition, year, is_first):
    if condition == "standing":
        first = f"I stood here in {year}."
    elif condition == "rebuilt":
        first = f"I was rebuilt in {year}."
    elif condition == "burnt":
        first = f"I burned in {year}."
    elif condition == "ruin":
        first = f"I lay in ruins in {year}."
    elif condition == "damaged":
        first = f"I was damaged in {year}."
    elif condition == "under_construction":
        first = (f"I was being built in {year}."
                 if is_first else f"I was being rebuilt in {year}.")
    elif condition == "moved":
        first = f"I moved in {year}."
    else:
        first = f"I was here in {year}."
    return first


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


def end_sources(claims) -> list:
    """Unique sources behind the verified claims: URL kept for the web
    page, site plus title for the film end card."""
    seen = []
    entries = []
    for claim in claims:
        url = claim.get("url")
        if url and url not in seen and claim.get("verdict") in ("supported", "partly"):
            seen.append(url)
            entries.append({"url": url, "site": source_site(url),
                            "title": source_title(url)})
    return entries


def scene_site(scene, claims=()) -> str:
    """On-screen source for one scene: its caption lines first, then
    the verified claims of its year, so every scene names a source."""
    for line in scene.get("caption_lines", []):
        if line.get("url"):
            return source_site(line["url"])
    for claim in claims:
        if (claim.get("year") == scene.get("from_year")
                and claim.get("url")
                and claim.get("verdict") in ("supported", "partly")):
            return source_site(claim["url"])
    return ""


def build_timeline(scenes, images, claims=()) -> list:
    """Contiguous segments: title, anchor, one era per painting, today, end."""
    plan = [{"kind": "title", "start": 0, "end": TITLE_S}]
    plan.append({"kind": "anchor", "start": TITLE_S, "end": TITLE_S + ANCHOR_S})
    eras = [s for s in scenes if isinstance(s.get("from_year"), int)
            and str(s["from_year"]) in images]
    t = TITLE_S + ANCHOR_S
    for position, scene in enumerate(eras):
        year = scene["from_year"]
        line1, line2 = caption_for(scene, is_first=(position == 0))
        plan.append({"kind": "era", "year": year,
                     "date_label": scene.get("date_label", str(year)),
                     "image": images[str(year)], "start": t, "end": t + ERA_S,
                     "caption": [line1, line2], "site": scene_site(scene, claims)})
        t += ERA_S
    plan.append({"kind": "today", "start": t, "end": t + TODAY_S})
    plan.append({"kind": "end", "start": t + TODAY_S,
                 "end": t + TODAY_S + END_S})
    return plan


def write_film(out_dir, research, images, photo, photo_credit, layers,
               place="", era_files=None, layer_files=None, photo_file=None,
               cutout_file=None):
    """film.json plus film.html plus copied assets under out_dir/film/."""
    out_dir = Path(out_dir)
    film_dir = out_dir / "film"
    film_dir.mkdir(parents=True, exist_ok=True)
    name = research["object"]["name"]
    claims = research.get("claims", [])
    scenes = [s for s in research.get("scenes", []) if isinstance(s.get("from_year"), int)]
    plan = build_timeline(research.get("scenes", []), images, claims)
    painted = {e["year"]: e["t"] for e in research.get("stream", [])
               if e["event"] == "scene_painted" and e.get("verdict") == "matches"}
    film_scenes = []
    for scene in scenes:
        key = str(scene["from_year"])
        if key not in images:
            continue
        line1, line2 = caption_for(
            scene, is_first=(scene["from_year"] == scenes[0]["from_year"]))
        stored = scene.get("caption_sentence") or {}
        cited = None
        if stored.get("text"):
            cited = {"year": stored.get("claim_year"),
                     "url": stored.get("claim_url")}
        film_scenes.append({"year": scene["from_year"],
                            "date_label": scene.get("date_label", key),
                            "image": images[key], "caption": [line1, line2],
                            "site": scene_site(scene, claims),
                            "caption_claim": cited,
                            "layers": (layers or {}).get(key, []),
                            "ready_at": painted.get(scene["from_year"], 0)})
    attribution = []
    if research.get("timings", {}).get("identify_steps", {}).get("overpass_s") is not None:
        attribution.append("© OpenStreetMap contributors")
    film = {"object": name, "place": place, "photo": photo,
            "photo_credit": photo_credit,
            "cutout": ("cutout.png" if cutout_file is not None else None),
            "attribution": attribution,
            "ai_label": "Painted scenes are AI imagery, checked against verified sources.",
            "sources": end_sources(research.get("claims", [])),
            "segments": plan, "scenes": film_scenes}
    (film_dir / "film.json").write_text(json.dumps(film, indent=1))
    template = (Path(__file__).parent / "film.html").read_text()
    embedded = json.dumps(film).replace("</", "<\\/")
    tag = ('<script id="film-data" type="application/json">'
           "__FILM_JSON__</script>")
    assert tag in template
    (film_dir / "film.html").write_text(
        template.replace(tag, tag.replace("__FILM_JSON__", embedded)))
    for dest, src in [("today.jpg", photo_file)] + [
            (f"era_{key}.png", src) for key, src in (era_files or {}).items()]:
        if src is not None:
            shutil.copy(src, film_dir / dest)
    for key, files in (layer_files or {}).items():
        layer_dir = film_dir / f"layers_{key}"
        layer_dir.mkdir(exist_ok=True)
        for i, src in enumerate(files):
            shutil.copy(src, layer_dir / f"figure_{i}.png")
    if cutout_file is not None:
        shutil.copy(cutout_file, film_dir / "cutout.png")
    return film_dir
