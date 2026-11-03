"""Evidence pages: what the film asserts, with the bound quotes,
sources, models and verdicts behind each scene. Read-only over the
stored files: quotes are copied literally, never rewritten."""

import html
import json
from pathlib import Path

from witness import models

STYLE = """
body{font-family:Georgia,'Times New Roman',serif;line-height:1.6;
max-width:46rem;margin:0 auto;padding:1.5rem;color:#211b12;background:#fffdf7}
h1{font-size:1.6rem}
h2{font-size:1.2rem;margin-top:2.5rem;border-top:1px solid #e0d3b8;padding-top:1rem}
img{max-width:100%;height:auto}
blockquote.quote{background:#f7f1e3;border-left:4px solid #84301f;
margin:1rem 0;padding:.75rem 1rem}
p.source{font-size:.9rem;overflow-wrap:break-word}
table.steps{border-collapse:collapse;width:100%;font-size:.9rem;
font-family:-apple-system,'Segoe UI',Roboto,sans-serif}
table.steps th,table.steps td{border:1px solid #e0d3b8;padding:.35rem .6rem;
text-align:left;vertical-align:top}
p.provenance{font-size:.85rem;color:#57503f}
"""


def _wiring_label() -> str:
    from witness.cli import verify_wiring

    return verify_wiring("baseten")["support_label"]


def _load(root):
    root = Path(root)
    research = json.loads((root / "research.json").read_text())
    manifest = json.loads((root / "paint_parallel_strict.json").read_text())
    film = json.loads((root / "film" / "film.json").read_text())
    return research, manifest, film


def _claim_for(claims, year, url):
    for claim in claims:
        if claim.get("year") == year and claim.get("url") == url:
            return claim
    for claim in claims:
        if claim.get("year") == year:
            return claim
    return None


def _scene_block(scene, filmed, claims, paintings, votes_label):
    stored = filmed.get("caption") or ["", ""]
    stamp, sentence = stored[0], stored[1]
    caption = scene.get("caption_sentence") or {}
    ev = caption.get("evidence") or {}
    child = (caption.get("child") or {}).get("text", "")
    state = (scene.get("state") or {}).get("description", "")
    claim = _claim_for(claims, caption.get("claim_year"),
                       caption.get("claim_url"))
    painting = paintings.get(filmed.get("year"))
    quote = ev.get("quote", "")
    url = ev.get("url", "")
    esc = html.escape
    parts = [f"<h2>{esc(str(stamp))}: {esc(sentence)}</h2>"]
    parts.append(f'<img src="{esc(filmed.get("image", ""))}" '
                 f'alt="Painted era: {esc(str(stamp))}">')
    parts.append(f"<p><strong>Caption:</strong> {esc(sentence)}</p>")
    if child:
        parts.append(f"<p><strong>Picture-book:</strong> {esc(child)}</p>")
    if state:
        parts.append(f"<p><strong>Checked state:</strong> {esc(state)}</p>")
    parts.append(f'<blockquote class="quote" data-url="{esc(url)}">'
                 f"{esc(quote)}</blockquote>")
    parts.append(f'<p class="source">Source: <a href="{esc(url)}">'
                 f"{esc(url)}</a></p>")
    if claim is not None:
        kept = [entry for entry in claim.get("support", [])
                if entry.get("supports") and entry.get("quote")]
        if kept:
            parts.append("<p><strong>Other kept sentences:</strong></p><ul>")
            for entry in kept:
                if entry["quote"] == quote:
                    continue
                parts.append(
                    f'<li><blockquote class="quote" data-url="'
                    f'{esc(entry.get("url", ""))}">'
                    f"{esc(entry['quote'])}</blockquote></li>")
            parts.append("</ul>")
    verdict = claim.get("verdict", "?") if claim else "?"
    votes = claim.get("votes", "?") if claim else "?"
    paint_verdict = painting.get("verdict", "?") if painting else "?"
    attempts = painting.get("attempts", "?") if painting else "?"
    binding = (painting.get("binding", "") or "")[:12] if painting else ""
    rows = [
        ("Research", f"Muse Spark ({models.RESEARCH.model})",
         "claim proposed"),
        ("Support votes", f"{votes_label}, Meta fallback",
         f"{verdict}, {votes} vote(s)"),
        ("Caption check", f"{votes_label}, Meta fallback",
         "verified, quote bound" if quote else "no bound quote"),
        ("Painting", f"Muse Image ({models.PAINT.model})",
         f"{attempts} attempt(s)"),
        ("Painting check",
         f"Muse Spark ({models.CHECK.model}, vision)", paint_verdict
         + (f", binding {binding}" if binding else "")),
    ]
    parts.append('<table class="steps"><tr><th>Step</th><th>Model</th>'
                 "<th>Recorded verdict</th></tr>")
    for step, model, recorded in rows:
        parts.append(f"<tr><td>{esc(step)}</td><td>{esc(model)}</td>"
                     f"<td>{esc(str(recorded))}</td></tr>")
    parts.append("</table>")
    return "\n".join(parts)


def _refused_block(claim):
    esc = html.escape
    urls = sorted({entry.get("url", "") for entry in claim.get("support", [])
                   if entry.get("url")})
    year = esc(str(claim.get("year", "")))
    parts = [f"<h2>Left out: {year}</h2>",
             f'<p class="claim">{esc(claim.get("claim", ""))}</p>',
             f"<p>Verdict: {esc(claim.get('verdict', ''))}."
             + (f" {esc(claim.get('note', ''))}."
                if claim.get("note") else "")
             + "</p>"]
    if urls:
        parts.append("<p>Checked against:</p><ul>")
        for url in urls:
            parts.append(f'<li><a href="{esc(url)}">{esc(url)}</a></li>')
        parts.append("</ul>")
    return "\n".join(parts)


def build_page(slug_dir, refused_year=None) -> str:
    """The evidence page for one example: filmed scenes with their
    bound quotes and step verdicts, plus one refused claim. Every
    quote is copied literally from the stored files."""
    slug_dir = Path(slug_dir)
    research, manifest, film = _load(slug_dir)
    scenes = {scene.get("from_year"): scene
              for scene in research.get("scenes", [])}
    entries = {entry.get("year"): entry
               for entry in manifest.get("eras", [])}
    votes_label = _wiring_label()
    esc = html.escape
    name = research.get("object", {}).get("name", slug_dir.name)
    parts = ["<!doctype html>", '<html lang="en">',
             f"<head><meta charset=\"utf-8\">"
             f"<title>Evidence: {esc(name)}</title>"
             f"<style>{STYLE}</style></head>", "<body>",
             f"<h1>Evidence: {esc(name)}</h1>",
             "<p class=\"provenance\">What the film asserts, with the "
             "bound quotes, sources, models and recorded verdicts. "
             "Quotes are copied literally from the stored research; "
             "nothing here is rewritten.</p>"]
    for filmed in film.get("scenes", []):
        scene = scenes.get(filmed.get("year"))
        if scene is None:
            continue
        parts.append(_scene_block(scene, filmed, research.get("claims", []),
                                  entries, votes_label))
    refused = [claim for claim in research.get("claims", [])
               if claim.get("verdict") != "supported"]
    chosen = None
    if refused_year is not None:
        chosen = next((claim for claim in refused
                       if claim.get("year") == refused_year), None)
    elif refused:
        chosen = refused[0]
    if chosen is not None:
        parts.append(_refused_block(chosen))
    parts.append("</body></html>")
    return "\n".join(parts)


def write_page(slug_dir, refused_year=None):
    """Write film/evidence.html for one example; return its path."""
    slug_dir = Path(slug_dir)
    dest = slug_dir / "film" / "evidence.html"
    dest.write_text(build_page(slug_dir, refused_year),
                    encoding="utf-8")
    return dest


def cmd_evidence(slug, out_dir="out", refused_year=None) -> int:
    """Build the evidence page from an example's stored files."""
    slug_dir = Path(out_dir) / slug
    if not (slug_dir / "research.json").exists():
        print(f"no research at {slug_dir / 'research.json'}")
        return 2
    dest = write_page(slug_dir, refused_year)
    print(f"evidence at {dest}")
    return 0
