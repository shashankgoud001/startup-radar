"""Turn the raw YC dump into a normalised, readable startup corpus.

Everything here is derivation, never invention: fields are copied from the
source, bucketed, or parsed out of text that the company wrote about itself.
Where a value is an inference (founding year from batch, geography from a
location string, "probably dead" from a dead website) the field name says so.
"""

import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "yc_companies.json"
LIVENESS_PATH = ROOT / "data" / "raw" / "liveness.json"
CORPUS_PATH = ROOT / "data" / "startups.json"
CSV_PATH = ROOT / "data" / "startups.csv"
SUMMARY_PATH = ROOT / "data" / "summary.json"

SOURCE = "ycombinator"

#: Windows relative to the year the corpus was built.
RECENT_YEARS = 10
FOCUS_YEARS = 5

#: YC mixes geographic regions and countries in `regions`. Europe is taken as
#: the EU plus the UK, EEA and Switzerland, and the western Balkans/Ukraine.
#: Russia, Belarus and Turkey sit in YC's data but not in this bucket.
EUROPE_COUNTRIES = {
    "united kingdom", "ireland", "germany", "france", "spain", "portugal",
    "italy", "netherlands", "belgium", "luxembourg", "austria", "switzerland",
    "denmark", "sweden", "norway", "finland", "iceland", "poland", "czechia",
    "slovakia", "hungary", "romania", "bulgaria", "greece", "croatia",
    "slovenia", "estonia", "latvia", "lithuania", "malta", "cyprus", "ukraine",
    "serbia", "bosnia and herzegovina", "north macedonia", "albania",
    "montenegro", "moldova",
}

COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "uae": "United Arab Emirates",
    "south korea": "South Korea",
    "korea": "South Korea",
    "czech republic": "Czechia",
    "vietnam": "Vietnam",
}

#: Text the company itself wrote about an exit. Kept as evidence, not truth:
#: the matched sentence travels with the parse so a human can check it.
#: A wide window after "acquired by", then cut at the first clause boundary.
#: The two-step matters: companies write "Acquired by Farfetch (NASDAQ: FTCH)
#: in Dec 2021" and "acquired by Google and now part of X", and a single
#: regex either grabs the parenthesis or swallows the rest of the sentence.
ACQUIRED_RE = re.compile(r"acquired\s+by\s+(?P<window>[^.;\n]{1,140})", re.IGNORECASE)
CLAUSE_STOP_RE = re.compile(
    r"\s+(?:in|on|for|to|and|now|which|where|by|from|at|as|that|with|after|since|during|via)\s"
    r"|[,;:(]|\)"
)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SHUTDOWN_RE = re.compile(
    r"(?:shut\s+down|shuttered|ceased\s+operations|closed\s+(?:its\s+)?(?:doors|down)|wound\s+down)"
    r"[^.\n]{0,40}?(?:(?:in|on)\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)

DEFUNCT_SITE_STATES = {"gone", "unreachable"}

CSV_COLUMNS = [
    "name", "market", "hq_city", "hq_country", "batch", "batch_year",
    "years_since_batch", "recent_10y", "recent_5y", "industries", "tags",
    "product", "product_detail", "team_size", "stage", "is_hiring",
    "top_company", "status", "outcome", "likely_defunct", "status_note",
    "acquired_by", "exit_year", "exit_source", "exit_evidence",
    "website", "site_state", "site_http_status",
    "yc_url", "slug",
]


def clean(text) -> str:
    """Collapse the source's stray newlines and whitespace, keep the words."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).replace("\r", " ")).strip()


def split_batch(batch: str) -> tuple:
    """"Winter 2027" -> ("Winter", 2027). Unknown shapes give ("", None)."""
    parts = (batch or "").split()
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    if len(parts) == 1 and parts[0].isdigit():
        return "", int(parts[0])
    return "", None


def parse_locations(all_locations: str) -> tuple:
    """"Austin, TX, USA; Remote" -> ("Austin", "United States")."""
    if not all_locations:
        return "", ""
    places = [p.strip() for p in all_locations.split(";") if p.strip()]
    places = [p for p in places if p.lower() != "remote"]
    if not places:
        return "", ""
    parts = [p.strip() for p in places[0].split(",") if p.strip()]
    if not parts:
        return "", ""
    city = parts[0]
    country = parts[-1] if len(parts) >= 2 else ""
    country = COUNTRY_ALIASES.get(country.lower(), country)
    return city, country


def market_of(regions, hq_country: str) -> str:
    """Primary target market, or "" when the company sits outside the three."""
    names = {str(r).strip().lower() for r in (regions or [])}
    names.add(hq_country.lower())
    if "india" in names:
        return "India"
    if "united states of america" in names or "united states" in names:
        return "United States"
    if "europe" in names or names & EUROPE_COUNTRIES:
        return "Europe"
    return ""


def _acquirer_from(window: str) -> str:
    """The shortest sensible company name from the text after "acquired by"."""
    stop = CLAUSE_STOP_RE.search(window)
    text = (window[: stop.start()] if stop else window).strip(" ,.;:-\u2014*")
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE).strip()
    if not text or not text[0].isupper() or len(text.split()) > 6:
        return ""
    return text


def parse_exit(detail: str, status: str) -> dict:
    """Pull an acquisition or shutdown out of the description, with evidence.

    A company whose YC status is not Acquired can still write "acquired by"
    mid-sentence about someone else (a customer, a partner), so for those we
    only trust a preamble hit near the start of the description.
    """
    found = {"acquired_by": "", "exit_year": None, "exit_evidence": "", "exit_source": ""}
    if not detail:
        return found

    trusted = (status or "").lower() == "acquired"
    for match in ACQUIRED_RE.finditer(detail):
        if not trusted and match.start() > 120:
            continue
        window = match.group("window")
        acquirer = _acquirer_from(window)
        found["acquired_by"] = acquirer
        found["exit_evidence"] = clean(detail[match.start() : match.end()])[:180]
        found["exit_source"] = "yc_status" if trusted else "description"
        year = YEAR_RE.search(window)
        found["exit_year"] = int(year.group(1)) if year else None
        return found

    match = SHUTDOWN_RE.search(detail)
    if match:
        found["exit_year"] = int(match.group("year")) if match.group("year") else None
        found["exit_evidence"] = clean(match.group(0))[:180]
        found["exit_source"] = "description"
    return found


def outcome_of(status: str) -> str:
    return {
        "active": "operating",
        "inactive": "inactive",
        "acquired": "acquired",
        "public": "public",
    }.get((status or "").lower(), "unknown")


def status_note(row: dict) -> str:
    """One line a human can read: what happened to this company?"""
    outcome = row["outcome"]
    if outcome == "acquired":
        if row["acquired_by"]:
            year = f" in {row['exit_year']}" if row["exit_year"] else ""
            note = f"Acquired by {row['acquired_by']}{year}"
        else:
            note = "Acquired (acquirer not named in its own description)"
    elif outcome == "public":
        note = "Went public"
    elif outcome == "inactive":
        note = "Inactive on YC (delisted or wound down)"
    elif outcome == "operating":
        note = "Active"
    else:
        note = "Unknown"

    if row["site_state"] == "gone":
        note += "; website returns 404/410"
    elif row["site_state"] == "unreachable":
        note += "; website unreachable"
    elif row["site_state"] == "server_error":
        note += "; website erroring (5xx)"
    return note


def load_liveness() -> dict:
    if not LIVENESS_PATH.exists():
        return {}
    data = json.loads(LIVENESS_PATH.read_text(encoding="utf-8"))
    return data.get("domains", data)


def domain_of(url: str) -> str:
    match = re.match(r"https?://([^/?#]+)", url or "", re.IGNORECASE)
    if not match:
        return ""
    host = match.group(1).lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def build_rows(companies: list, liveness: dict, reference_year: int) -> list:
    rows = []
    for company in companies:
        batch = clean(company.get("batch"))
        season, year = split_batch(batch)
        city, country = parse_locations(clean(company.get("all_locations")))
        product = clean(company.get("one_liner"))
        detail = clean(company.get("long_description"))

        if not product and detail:
            product = detail.split(". ")[0].rstrip(".") + "."

        exit_info = parse_exit(detail, clean(company.get("status")))
        website = clean(company.get("website"))
        site = liveness.get(domain_of(website)) or {}

        row = {
            "id": company.get("id"),
            "name": clean(company.get("name")),
            "slug": clean(company.get("slug")),
            "former_names": company.get("former_names") or [],
            "website": website,
            "yc_url": clean(company.get("url")),
            # when
            "batch": batch,
            "batch_season": season,
            "batch_year": year,
            "years_since_batch": (reference_year - year) if year else None,
            "recent_10y": bool(year and year >= reference_year - RECENT_YEARS),
            "recent_5y": bool(year and year >= reference_year - FOCUS_YEARS),
            "launched_at": (
                datetime.fromtimestamp(company["launched_at"], tz=timezone.utc)
                .date()
                .isoformat()
                if company.get("launched_at")
                else ""
            ),
            # where
            "hq_city": city,
            "hq_country": country,
            "all_locations": clean(company.get("all_locations")),
            "regions": company.get("regions") or [],
            "market": market_of(company.get("regions"), country),
            # what they sell
            "product": product,
            "product_detail": detail,
            "industry": clean(company.get("industry")),
            "subindustry": clean(company.get("subindustry")),
            "industries": company.get("industries") or [],
            "tags": company.get("tags") or [],
            # size and traction
            "team_size": company.get("team_size"),
            "stage": clean(company.get("stage")),
            "is_hiring": bool(company.get("isHiring")),
            "top_company": bool(company.get("top_company")),
            # outcome
            "status": clean(company.get("status")),
            "outcome": outcome_of(company.get("status")),
            "acquired_by": exit_info["acquired_by"],
            "exit_year": exit_info["exit_year"],
            "exit_source": exit_info["exit_source"],
            "exit_evidence": exit_info["exit_evidence"],
            # website health
            "site_state": site.get("state", ""),
            "site_http_status": site.get("status"),
            "site_final_url": site.get("final_url", ""),
            "site_checked_at": site.get("checked_at", ""),
            # provenance
            "source": SOURCE,
            "description_source": (
                "yc_one_liner" if company.get("one_liner") else
                "yc_long_description" if detail else ""
            ),
            "fetched_at": "",
        }
        row["likely_defunct"] = (
            row["outcome"] == "inactive" or row["site_state"] in DEFUNCT_SITE_STATES
        )
        row["status_note"] = status_note(row)
        rows.append(row)

    rows.sort(key=lambda r: (r["name"].lower(), r["id"] or 0))
    return rows


def dedupe(rows: list) -> tuple:
    """Drop repeat slugs, keeping the record with the most description text."""
    kept, index, dropped = [], {}, 0
    for row in rows:
        key = row["slug"] or f"id:{row['id']}"
        if key not in index:
            index[key] = len(kept)
            kept.append(row)
            continue
        dropped += 1
        existing = kept[index[key]]
        if len(row["product_detail"]) > len(existing["product_detail"]):
            kept[index[key]] = row
    return kept, dropped


def write_json(rows: list) -> None:
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(
        json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_csv(rows: list) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            record = dict(row)
            for field in ("industries", "tags"):
                record[field] = "; ".join(record[field])
            writer.writerow(record)


def summarise(rows: list) -> dict:
    from collections import Counter

    return {
        "total": len(rows),
        "recent_10y": sum(1 for r in rows if r["recent_10y"]),
        "recent_5y": sum(1 for r in rows if r["recent_5y"]),
        "with_website": sum(1 for r in rows if r["website"]),
        "with_long_description": sum(1 for r in rows if r["product_detail"]),
        "likely_defunct": sum(1 for r in rows if r["likely_defunct"]),
        "outcome": dict(Counter(r["outcome"] for r in rows).most_common()),
        "market": dict(Counter(r["market"] or "Outside target" for r in rows).most_common()),
        "site_state": dict(Counter(r["site_state"] or "not checked" for r in rows).most_common()),
        "by_market_and_year": {
            market: {
                str(year): count
                for year, count in sorted(
                    Counter(
                        r["batch_year"] for r in rows if (r["market"] or "") == market
                    ).items()
                )
            }
            for market in ("India", "United States", "Europe")
        },
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not RAW_PATH.exists():
        print(f"missing {RAW_PATH}; run tools/fetch_yc.py first", file=sys.stderr)
        return 1

    companies = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    liveness = load_liveness()
    reference_year = date.today().year
    fetched_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

    rows = build_rows(companies, liveness, reference_year)
    rows, dropped = dedupe(rows)
    for row in rows:
        row["fetched_at"] = fetched_at

    # Signals we cite at the row level need a timestamp of their own.
    if liveness:
        print(f"merged website checks for {len(liveness)} domains", file=sys.stderr)

    write_json(rows)
    recent = [r for r in rows if r["recent_10y"]]
    write_csv(recent)

    summary = summarise(rows)
    summary["duplicates_dropped"] = dropped
    summary["reference_year"] = reference_year
    summary["built_at"] = fetched_at
    summary["sources"] = [SOURCE]
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {CORPUS_PATH}\nwrote {CSV_PATH} ({len(recent)} rows, last {RECENT_YEARS}y)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
