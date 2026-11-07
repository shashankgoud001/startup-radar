"""Pick the technically substantial companies out of the corpus.

"Tech related" is useless as a filter here - every YC company is a tech
company. What is worth reading is the subset whose *product* is hard: models,
compilers, chips, robots, assays. YC tags already encode most of that, so tags
carry the weight and description wording only breaks ties.

Writes tech_picks.md, grouped into themes, newest and best-described first.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "startups.json"
OUT_PATH = ROOT / "tech_picks.md"

#: Minimum detail length. Below this the excerpt is not worth reading.
MIN_DETAIL = 180

#: Cumulative score needed to count as technical. One strong tag scores 3,
#: a matching industry 2, a technical word in the one-liner 2, in the body 1.
THRESHOLD = 4

#: Consumer companies often carry "AI" or "Computer Vision" tags while selling
#: a shopping app. Technical tags alone should not pull them in.
CONSUMER_TAGS = {
    "e-commerce", "consumer", "marketplace", "retail", "social", "dating",
    "food and beverage", "home and personal", "travel", "beauty", "fashion",
    "gaming", "media", "content",
}
CONSUMER_INDUSTRIES = {"consumer", "retail", "housing and real estate"}

PER_THEME = 14


class Theme:
    def __init__(self, slug, title, blurb, tags, industries=(), words=""):
        self.slug = slug
        self.title = title
        self.blurb = blurb
        self.tags = {t.lower() for t in tags}
        self.industries = {i.lower() for i in industries}
        self.words = re.compile(words, re.IGNORECASE) if words else None


THEMES = [
    Theme(
        "ai",
        "AI and machine learning",
        "Model builders, inference, agents, vision and speech. The centre of "
        "gravity for the last five batches.",
        tags=[
            "AI", "Machine Learning", "Generative AI", "AI Assistant",
            "Computer Vision", "Deep Learning", "Natural Language Processing",
            "LLM", "Speech", "AI-Infrastructure",
        ],
        industries=["Machine Learning"],
        words=r"\b(llms?|models?|inference|training|agents?|transformers?|diffusion|"
              r"embeddings?|neural|vision|speech|fine-tun\w+|multimodal)\b",
    ),
    Theme(
        "infra",
        "Developer tools and infrastructure",
        "The layer below the product: runtimes, databases, build tools, "
        "observability. Usually built by people who were annoyed enough to "
        "rewrite something.",
        tags=[
            "Developer Tools", "Open Source", "API", "Infrastructure",
            "Data Engineering", "Databases", "DevOps", "Cloud Infrastructure",
            "Observability", "Engineering, Product and Design",
        ],
        industries=["Infrastructure"],
        words=r"\b(compilers?|runtimes?|databases?|kubernetes|containers?|sdks?|apis?|"
              r"open[- ]source|observability|ci/cd|serverless|query|pipelines?|"
              r"distributed|latency)\b",
    ),
    Theme(
        "hard",
        "Hard tech, robotics and space",
        "Atoms, not software: chips, robots, satellites, batteries. The "
        "longest timelines and the most interesting failure modes.",
        tags=[
            "Hard Tech", "Hardware", "Robotics", "Semiconductors", "Climate",
            "Energy", "Aerospace", "Space", "Automation", "Drones",
            "Manufacturing", "IoT",
        ],
        industries=["Manufacturing and Robotics", "Aviation and Space", "Energy"],
        words=r"\b(robots?|satellites?|chips?|semiconductors?|batter(?:y|ies)|sensors?|"
              r"manufactur\w+|rockets?|drones?|lasers?|actuators?|motors?)\b",
    ),
    Theme(
        "security",
        "Security",
        "Attack surface, identity and supply chain. Small market, unforgiving "
        "product bar.",
        tags=["Security", "Cybersecurity", "Privacy", "Identity"],
        industries=["Security"],
        words=r"\b(threat|vulnerab\w+|malware|encryption|zero[- ]trust|"
              r"attack surface|compliance|pentest\w*|secrets?)\b",
    ),
    Theme(
        "bio",
        "Bio and health technology",
        "Wet labs, drug discovery, diagnostics and clinical software. The "
        "place where 'move fast' has a different cost.",
        tags=[
            "Biotech", "Drug Discovery", "Therapeutics", "Health Tech",
            "Digital Health", "Medical Devices", "Genomics", "BioTech",
            "Healthcare IT", "Life Sciences",
        ],
        industries=["Therapeutics", "Drug Discovery and Delivery", "Healthcare IT"],
        words=r"\b(genom\w+|molecul\w+|protein\w*|assays?|clinical|diagnos\w+|"
              r"therapeutic\w*|biomarker\w*|crispr|cells?)\b",
    ),
]


def normalise(values):
    return {str(v).strip().lower() for v in values}


def score_themes(row):
    """Return {slug: (score, signals)} for every theme this row touches."""
    tags = normalise(row["tags"])
    industries = normalise(row["industries"])
    one_liner = (row["product"] or "").lower()
    detail = (row["product_detail"] or "").lower()

    scores = {}
    for theme in THEMES:
        score, signals = 0, []
        matched = tags & theme.tags
        if matched:
            score += 3 * len(matched)
            signals.extend(sorted(matched)[:3])
        # Drop bare acronyms: "ai" as a signal just restates the theme.
        signals = [s for s in signals if len(s) > 2]
        if industries & theme.industries:
            score += 2
            signals.append(sorted(industries & theme.industries)[0])
        if theme.words:
            hit = theme.words.search(one_liner)
            if hit:
                score += 2
                signals.append(hit.group(0).lower())
            elif theme.words.search(detail):
                score += 1

        penalty = 2 * len(tags & CONSUMER_TAGS) + 2 * len(industries & CONSUMER_INDUSTRIES)
        if penalty:
            score -= min(penalty, 5)
        if score > 0:
            scores[theme.slug] = (score, signals)
    return scores


def pick(rows, threshold=THRESHOLD, per_theme=PER_THEME):
    chosen = {}
    for row in rows:
        if not row["recent_10y"] or len(row["product_detail"] or "") < MIN_DETAIL:
            continue
        scores = score_themes(row)
        if not scores:
            continue
        slug, (score, signals) = max(scores.items(), key=lambda kv: kv[1][0])
        if score < threshold:
            continue
        chosen.setdefault(slug, []).append(
            (score, row, signals, sorted(scores, key=lambda s: -scores[s][0]))
        )

    picked = {}
    for slug, entries in chosen.items():
        entries.sort(
            key=lambda e: (
                -e[0],
                not e[1]["recent_5y"],
                len(e[1]["product_detail"] or ""),
            )
        )
        picked[slug] = entries[:per_theme]
    return picked


def excerpt(text: str, limit: int = 420) -> str:
    """First ~two sentences, cut on a sentence boundary where possible."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if stop > limit * 0.5:
        return cut[: stop + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "..."


def render(picked: dict, rows: list) -> str:
    total = sum(len(v) for v in picked.values())
    lines = [
        "# Tech picks",
        "",
        f"{total} companies pulled from the corpus: the ones whose product is "
        "genuinely technical, not merely delivered through software. Every row "
        f"here is from batch 2016 or later and has at least {MIN_DETAIL} "
        "characters of the company's own description.",
        "",
        "Generated by `tools/pick_tech.py` from `data/startups.json`. Re-run it "
        "after refreshing the corpus; edit the themes in that script to change "
        "what counts as technical.",
        "",
        "| Theme | Count |",
        "|---|---|",
    ]
    for theme in THEMES:
        if theme.slug in picked:
            lines.append(f"| [{theme.title}](#{theme.slug}) | {len(picked[theme.slug])} |")

    for theme in THEMES:
        entries = picked.get(theme.slug)
        if not entries:
            continue
        lines += ["", f'<a id="{theme.slug}"></a>', f"## {theme.title}", "", theme.blurb, ""]
        for score, row, signals, other in entries:
            meta = [
                row["market"] or row["hq_country"] or "?",
                row["batch"],
            ]
            if row["team_size"]:
                meta.append(f"{row['team_size']} people")
            if row["top_company"]:
                meta.append("YC top company")
            lines.append(f"### {row['name']}")
            lines.append("")
            lines.append(f"*{' · '.join(meta)}*")
            lines.append("")
            lines.append(f"**{row['product']}**")
            lines.append("")
            if row["product_detail"]:
                lines.append(f"> {excerpt(row['product_detail'])}")
                lines.append("")
            status = row["status_note"]
            lines.append(f"- Status: {status}")
            lines.append(f"- Tags: {', '.join(row['tags'][:8]) or '-'}")
            lines.append(f"- Matched on: {', '.join(signals) or '-'}")
            if other:
                titles = {t.slug: t.title for t in THEMES}
                lines.append(f"- Also fits: {', '.join(titles.get(o, o) for o in other)}")
            if row["website"]:
                lines.append(f"- Links: [{row['website']}]({row['website']}) · [YC]({row['yc_url']})")
            lines.append("")

    lines += [
        "",
        "## What is missing from this list",
        "",
        "Fintech, marketplaces, SaaS for a specific industry and consumer apps "
        "are filtered out on purpose, not because they are bad companies. If the "
        "next pass wants them, the tags are already in the corpus "
        "(`Fintech` 718, `Marketplace` 311, `E-commerce` 194).",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    per_theme = PER_THEME
    if "--per-theme" in argv:
        per_theme = int(argv[argv.index("--per-theme") + 1])

    rows = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    picked = pick(rows, per_theme=per_theme)
    OUT_PATH.write_text(render(picked, rows), encoding="utf-8")

    for theme in THEMES:
        entries = picked.get(theme.slug, [])
        names = ", ".join(entry[1]["name"] for entry in entries[:6])
        print(f"{theme.slug:10} {len(entries):3}  {names}")
    print(f"\nwrote {OUT_PATH} ({sum(len(v) for v in picked.values())} companies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
