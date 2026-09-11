#!/usr/bin/env python3
"""
Export a static, safe-to-share meme gallery.

This avoids exposing the Flask app over a public tunnel when the user only
wants to browse generated memes.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MEMES_DIR = ROOT / "output" / "memes"
OUT_DIR = ROOT / "output" / "static_gallery"
ASSETS_DIR = OUT_DIR / "assets"


def parse_metadata(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("MEME:"):
            data["template"] = line.split(":", 1)[1].strip()
        elif line.startswith("TOP TEXT:"):
            data["top_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("BOTTOM TEXT:"):
            data["bottom_text"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUGGESTED CAPTION FOR POSTING:"):
            data["caption"] = line.split(":", 1)[1].strip()
    return data


def collect_memes(limit: int, type_filter: str) -> list[dict]:
    if not MEMES_DIR.exists():
        return []

    rows = []
    for image_path in sorted(MEMES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = image_path.stat()
        metadata = parse_metadata(image_path.with_suffix(".txt"))
        template = metadata.get("template") or image_path.stem
        is_original = template.lower().startswith("original")
        if type_filter == "original" and not is_original:
            continue
        if type_filter == "classic" and is_original:
            continue
        rows.append({
            "source_path": image_path,
            "asset_name": image_path.name,
            "template": template,
            "is_original": is_original,
            "meme_type": "Original" if is_original else "Classic",
            "top_text": metadata.get("top_text", ""),
            "bottom_text": metadata.get("bottom_text", ""),
            "caption": metadata.get("caption", ""),
            "created_at": datetime.fromtimestamp(stat.st_mtime),
            "date_key": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
        })
        if len(rows) >= limit:
            break
    return rows


def meme_manifest(memes: list[dict]) -> list[dict]:
    return [
        {
            "filename": meme["asset_name"],
            "template": meme["template"],
            "type": meme["meme_type"],
            "is_original": meme["is_original"],
            "top_text": meme["top_text"],
            "bottom_text": meme["bottom_text"],
            "caption": meme["caption"],
            "created_at": meme["created_at"].isoformat(timespec="seconds"),
            "date_key": meme["date_key"],
        }
        for meme in memes
    ]


def render_html(memes: list[dict], title: str) -> str:
    generated = datetime.now().strftime("%b %-d, %Y %-I:%M %p")
    original_count = sum(1 for meme in memes if meme["is_original"])
    classic_count = len(memes) - original_count
    dates = sorted({meme["date_key"] for meme in memes}, reverse=True)
    cards = []
    for meme in memes:
        badge_class = "original" if meme["is_original"] else "classic"
        cards.append(f"""
        <article class="card" data-type="{html.escape(meme["meme_type"].lower())}" data-date="{html.escape(meme["date_key"])}" data-search="{html.escape(" ".join([meme["template"], meme["top_text"], meme["bottom_text"], meme["caption"]]).lower())}">
          <span class="badge {badge_class}">{html.escape(meme["meme_type"])}</span>
          <img src="assets/{html.escape(meme["asset_name"])}" alt="{html.escape(meme["template"])}" loading="lazy">
          <div class="meta">
            <strong>{html.escape(meme["template"])}</strong>
            <span>{html.escape(meme["created_at"].strftime("%b %-d, %Y %-I:%M %p"))}</span>
            <p>{html.escape(meme["top_text"])}</p>
            {f'<p class="bottom">{html.escape(meme["bottom_text"])}</p>' if meme["bottom_text"] else ''}
          </div>
        </article>
        """)

    date_buttons = "\n".join(
        f'<button type="button" data-date="{html.escape(date)}">{html.escape(date)}</button>'
        for date in dates[:14]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; color: #222; }}
    header {{ position: sticky; top: 0; z-index: 2; background: #171729; color: #fff; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.18); }}
    header h1 {{ margin: 0 0 4px; font-size: 22px; }}
    header p {{ margin: 0; color: #d8d8e6; font-size: 13px; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 18px 16px 40px; }}
    .summary {{ margin-bottom: 14px; color: #555; font-size: 14px; }}
    .controls {{ display: grid; gap: 10px; margin-bottom: 16px; }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .filters button {{ border: 1px solid #d8dce5; background: #fff; color: #333; border-radius: 999px; padding: 7px 10px; font: inherit; font-size: 13px; cursor: pointer; }}
    .filters button.active {{ background: #1a73e8; border-color: #1a73e8; color: #fff; }}
    .search {{ width: 100%; border: 1px solid #d8dce5; border-radius: 8px; padding: 10px 12px; font: inherit; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); gap: 16px; align-items: start; }}
    .card {{ position: relative; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.14); }}
    .card.hidden {{ display: none; }}
    .card img {{ display: block; width: 100%; height: auto; }}
    .badge {{ position: absolute; top: 9px; left: 9px; border-radius: 999px; padding: 4px 8px; font-size: 11px; font-weight: 700; box-shadow: 0 1px 4px rgba(0,0,0,.22); }}
    .badge.original {{ background: #e5f6ef; color: #116545; }}
    .badge.classic {{ background: #eef2ff; color: #33418a; }}
    .meta {{ padding: 10px 12px 12px; border-top: 1px solid #eee; }}
    .meta strong {{ display: block; font-size: 13px; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .meta span {{ display: block; color: #777; font-size: 12px; margin-top: 4px; }}
    .meta p {{ margin: 6px 0 0; color: #444; font-size: 12px; line-height: 1.35; }}
    .meta .bottom {{ color: #666; }}
    @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <p>Exported {html.escape(generated)}</p>
  </header>
  <main>
    <div class="summary"><span id="visible-count">{len(memes)}</span> shown · {original_count} original · {classic_count} classic · {len(memes)} exported</div>
    <div class="controls">
      <input id="search" class="search" type="search" placeholder="Search template, text, or caption">
      <div class="filters" id="type-filters">
        <button type="button" data-type="all" class="active">All</button>
        <button type="button" data-type="original">Originals</button>
        <button type="button" data-type="classic">Known Templates</button>
      </div>
      <div class="filters" id="date-filters">
        <button type="button" data-date="all" class="active">All Dates</button>
        {date_buttons}
      </div>
    </div>
    <section class="grid">
      {''.join(cards)}
    </section>
  </main>
  <script>
    const cards = Array.from(document.querySelectorAll('.card'));
    const visibleCount = document.getElementById('visible-count');
    const search = document.getElementById('search');
    let activeType = 'all';
    let activeDate = 'all';

    function setActive(containerId, attr, value) {{
      document.querySelectorAll('#' + containerId + ' button').forEach((btn) => {{
        btn.classList.toggle('active', btn.dataset[attr] === value);
      }});
    }}

    function applyFilters() {{
      const q = (search.value || '').trim().toLowerCase();
      let shown = 0;
      cards.forEach((card) => {{
        const typeOk = activeType === 'all' || card.dataset.type === activeType;
        const dateOk = activeDate === 'all' || card.dataset.date === activeDate;
        const searchOk = !q || (card.dataset.search || '').includes(q);
        const visible = typeOk && dateOk && searchOk;
        card.classList.toggle('hidden', !visible);
        if (visible) shown += 1;
      }});
      visibleCount.textContent = shown;
    }}

    document.getElementById('type-filters').addEventListener('click', (event) => {{
      if (!event.target.dataset.type) return;
      activeType = event.target.dataset.type;
      setActive('type-filters', 'type', activeType);
      applyFilters();
    }});

    document.getElementById('date-filters').addEventListener('click', (event) => {{
      if (!event.target.dataset.date) return;
      activeDate = event.target.dataset.date;
      setActive('date-filters', 'date', activeDate);
      applyFilters();
    }});

    search.addEventListener('input', applyFilters);
  </script>
</body>
</html>
"""


def export_gallery(limit: int, type_filter: str, title: str) -> Path:
    memes = collect_memes(limit=limit, type_filter=type_filter)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    for meme in memes:
        shutil.copy2(meme["source_path"], ASSETS_DIR / meme["asset_name"])

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps({
        "title": title,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(memes),
        "memes": meme_manifest(memes),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    index_path = OUT_DIR / "index.html"
    index_path.write_text(render_html(memes, title), encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a static meme gallery")
    parser.add_argument("--limit", type=int, default=48, help="Max images to export")
    parser.add_argument("--type", choices=["all", "original", "classic"], default="all")
    parser.add_argument("--title", default="Meme Gallery Export")
    args = parser.parse_args()

    path = export_gallery(limit=max(1, args.limit), type_filter=args.type, title=args.title)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
