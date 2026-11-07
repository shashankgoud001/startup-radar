"""Render the tech picks as a single static page for GitHub Pages.

One HTML file, inline CSS, a few lines of vanilla JS for the filter box. No
build step, no dependencies, nothing to break in a year. Output goes to docs/,
which is what GitHub Pages publishes.
"""

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pick_tech  # noqa: E402  (same directory, not a package)

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "startups.json"
#: GitHub Pages serves this directory (Settings -> Pages -> /docs).
SITE_DIR = ROOT / "docs"

STATUS_CLASS = {
    "operating": "ok",
    "acquired": "exit",
    "public": "exit",
    "inactive": "dead",
    "unknown": "dead",
}

CSS = """
:root{--bg:#fbfaf8;--fg:#191817;--muted:#6b6862;--line:#e2ded6;--card:#fff;
--ok:#1b6b3a;--okbg:#e6f2ea;--dead:#8a1f1f;--deadbg:#f8e9e9;--exit:#1f4d8a;--exitbg:#e8eef8}
@media (prefers-color-scheme:dark){:root{--bg:#131313;--fg:#eceae6;--muted:#9d998f;--line:#2c2b28;
--card:#1a1a19;--ok:#7fd6a2;--okbg:#17301f;--dead:#f0a3a3;--deadbg:#331a1a;--exit:#9cc2f5;--exitbg:#182436}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:50rem;margin:0 auto;padding:3.5rem 1.25rem 5rem}
header h1{font-size:1.9rem;line-height:1.2;margin:0 0 .6rem;letter-spacing:-.02em}
header p{margin:0 0 1rem;color:var(--muted)}
.stats{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;margin:1.6rem 0 2rem;font-size:.85rem;color:var(--muted)}
.stats b{color:var(--fg);font-weight:600}
nav{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:1.4rem}
nav a{font-size:.82rem;text-decoration:none;color:var(--fg);border:1px solid var(--line);
border-radius:999px;padding:.25rem .7rem;background:var(--card)}
nav a:hover{border-color:var(--muted)}
input[type=search]{width:100%;padding:.7rem .9rem;font:inherit;font-size:.95rem;
color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:.55rem;margin-bottom:2.4rem}
input[type=search]:focus{outline:2px solid var(--exit);outline-offset:1px}
h2{font-size:1.15rem;margin:3rem 0 .3rem;letter-spacing:-.01em}
.lede{color:var(--muted);font-size:.9rem;margin:0 0 1.4rem}
article{background:var(--card);border:1px solid var(--line);border-radius:.7rem;
padding:1.1rem 1.2rem;margin-bottom:.9rem}
article h3{margin:0 0 .15rem;font-size:1.02rem}
.meta{font-size:.78rem;color:var(--muted);margin-bottom:.55rem}
.pitch{font-weight:600;font-size:.94rem;margin:.2rem 0 .5rem}
.detail{font-size:.9rem;color:var(--fg);opacity:.85;margin:0 0 .7rem}
.pill{display:inline-block;font-size:.7rem;letter-spacing:.02em;padding:.1rem .45rem;
border-radius:999px;margin-right:.35rem;vertical-align:1px}
.pill.ok{color:var(--ok);background:var(--okbg)}
.pill.dead{color:var(--dead);background:var(--deadbg)}
.pill.exit{color:var(--exit);background:var(--exitbg)}
.tags{font-size:.74rem;color:var(--muted);margin-top:.35rem}
.tags span{display:inline-block;margin-right:.5rem}
a{color:inherit}
footer{margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--line);
font-size:.8rem;color:var(--muted)}
.hidden{display:none}
"""

JS = """
const input = document.getElementById('q');
const sections = [...document.querySelectorAll('section')];
input.addEventListener('input', () => {
  const q = input.value.trim().toLowerCase();
  for (const section of sections) {
    let shown = 0;
    for (const card of section.querySelectorAll('article')) {
      const hit = !q || card.dataset.search.includes(q);
      card.classList.toggle('hidden', !hit);
      if (hit) shown++;
    }
    section.classList.toggle('hidden', shown === 0);
  }
});
"""


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def card(row) -> str:
    meta = [row["market"] or row["hq_country"] or "?"]
    if row["batch"]:
        meta.append(row["batch"])
    if row["team_size"]:
        meta.append(f"{row['team_size']} people")
    if row["top_company"]:
        meta.append("YC top company")

    links = []
    if row["website"]:
        links.append(f'<a href="{esc(row["website"])}" rel="noopener">site</a>')
    if row["yc_url"]:
        links.append(f'<a href="{esc(row["yc_url"])}" rel="noopener">YC profile</a>')

    detail = pick_tech.excerpt(row["product_detail"] or "", 340)
    tags = "".join(f"<span>#{esc(t)}</span>" for t in row["tags"][:6])
    haystack = " ".join(
        [row["name"], row["product"], row["product_detail"], row["market"],
         row["hq_country"], row["batch"], " ".join(row["tags"])]
    ).lower()

    return f"""<article data-search="{esc(haystack)}">
  <h3>{esc(row["name"])}</h3>
  <div class="meta">{esc(" · ".join(meta))}</div>
  <p class="pitch">{esc(row["product"])}</p>
  <p class="detail">{esc(detail)}</p>
  <span class="pill {STATUS_CLASS.get(row["outcome"], "dead")}">{esc(row["status_note"])}</span>
  <div class="tags">{tags}{' · '.join(links)}</div>
</article>"""


def render(picked: dict, rows: list) -> str:
    total = sum(len(v) for v in picked.values())
    recent = sum(1 for theme in picked.values() for e in theme if e[1]["recent_5y"])

    nav = "".join(
        f'<a href="#{theme.slug}">{esc(theme.title)}</a>'
        for theme in pick_tech.THEMES
        if picked.get(theme.slug)
    )
    sections = []
    for theme in pick_tech.THEMES:
        entries = picked.get(theme.slug)
        if not entries:
            continue
        cards = "\n".join(card(entry[1]) for entry in entries)
        sections.append(
            f"""<section>
<h2 id="{theme.slug}">{esc(theme.title)}</h2>
<p class="lede">{esc(theme.blurb)}</p>
{cards}
</section>"""
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Startup Radar — technical picks</title>
<meta name="description" content="{total} technically ambitious startups from Y Combinator, 2016 to 2026, with what each one sells and whether it still exists.">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Startup Radar</h1>
<p>{total} technically ambitious companies from Y&nbsp;Combinator, batch 2016 onward — with what each one actually sells and what happened to it.</p>
<div class="stats">
<span><b>{total}</b> companies</span>
<span><b>{recent}</b> from the last five batches</span>
<span><b>{len([t for t in pick_tech.THEMES if picked.get(t.slug)])}</b> themes</span>
</div>
</header>
<nav>{nav}</nav>
<input id="q" type="search" placeholder="Filter by name, tag, market or wording in the description…" aria-label="Filter companies">
{chr(10).join(sections)}
<footer>
<p>Descriptions are the companies' own words, from Y Combinator's public company index via the <a href="https://github.com/yc-oss/api" rel="noopener">yc-oss mirror</a>. Status combines YC's own state with a live check of each company's website.</p>
<p>Selected by tag and product wording, not by hand — see <code>tools/pick_tech.py</code>. Consumer apps, marketplaces and fintech are filtered out on purpose.</p>
</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main(argv=None) -> int:
    if not CORPUS_PATH.exists():
        print(f"missing {CORPUS_PATH}; run tools/build_corpus.py first", file=sys.stderr)
        return 1

    rows = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    picked = pick_tech.pick(rows)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(render(picked, rows), encoding="utf-8")
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    slim = [
        {
            "name": row["name"],
            "theme": theme.slug,
            "product": row["product"],
            "description": row["product_detail"],
            "market": row["market"],
            "country": row["hq_country"],
            "batch": row["batch"],
            "batch_year": row["batch_year"],
            "team_size": row["team_size"],
            "status": row["status"],
            "outcome": row["outcome"],
            "status_note": row["status_note"],
            "acquired_by": row["acquired_by"],
            "tags": row["tags"],
            "website": row["website"],
            "site_state": row["site_state"],
            "yc_url": row["yc_url"],
        }
        for theme in pick_tech.THEMES
        for score, row, signals, other in picked.get(theme.slug, [])
    ]
    (SITE_DIR / "picks.json").write_text(
        json.dumps(slim, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    size = (SITE_DIR / "index.html").stat().st_size
    print(f"wrote {SITE_DIR / 'index.html'} ({size // 1024} KB, {len(slim)} companies)")
    print(f"wrote {SITE_DIR / 'picks.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
