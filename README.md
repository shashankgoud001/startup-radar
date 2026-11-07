# Startup Radar

A local corpus of startups founded in roughly the last decade, weighted to the
last five years, with the thing you actually want to read: **what each one
sells**, in their own words, plus **what happened to it**.

## What this is

One source, cleaned properly, plus one independent signal that the source
doesn't give you (whether the website is still alive). Coverage:

| Slice | Companies |
|---|---|
| All launched, any year | 6,374 |
| Batch 2016 or later (`recent_10y`) | 5,449 |
| Batch 2021 or later (`recent_5y`) | 3,901 |
| … United States | 4,777 |
| … Europe | 507 |
| … India | 230 |
| … outside those three | 860 |
| Has a long description (not just a one-liner) | 5,944 (93%) |
| Flagged possibly defunct | 1,442 (23%) |

Source: [yc-oss/api](https://github.com/yc-oss/api), a mirror rebuilt daily from
Y Combinator's public company index. Public company-written copy, not scraped
from anyone's paid database.

## What this is not

Not a census of all startups in India/USA/Europe, and not a funding database.
It is YC-backed companies only, so it over-represents US software and
under-represents Indian and European ecosystems — India at 230 rows is a
sample, not a list of Indian startups. Treat the geography as a starting frame
and add sources before drawing conclusions about any market.

There are no funding amounts, no valuations and no founder names: the upstream
data does not carry them, and inventing them would be worse than leaving them
out.

## Files

```
data/startups.json        full corpus, all 6,374, one object per company
data/startups.csv         the working set: 5,449 rows, last 10 years, 30 cols
data/summary.json         counts by market, year, outcome and site health
data/raw/yc_companies.json  untouched upstream payload (11 MB)
data/raw/liveness.json      per-domain website check, cached and resumable
tools/fetch_yc.py         download (skips if the cache is under a day old)
tools/check_liveness.py   one HEAD request per domain, 40 threads, ~3 minutes
tools/build_corpus.py     normalise, derive, write json + csv + summary
tools/pick_tech.py        select the technical subset by theme -> tech_picks.md
tools/build_site.py       render docs/index.html + docs/picks.json
tech_picks.md             70 technically substantial companies, grouped by theme
docs/                     the published page; GitHub Pages serves this directory
```

`data/` is generated and not committed — run the three refresh commands
below to rebuild it.

Standard library only. No install step.

## Refreshing

```bash
python3 tools/fetch_yc.py --force     # new data
python3 tools/check_liveness.py       # re-probe stale domains only
python3 tools/build_corpus.py         # rebuild corpus, csv, summary
python3 tools/pick_tech.py            # rebuild tech_picks.md
python3 tools/build_site.py           # rebuild docs/ for the website
```

`check_liveness.py` caches for 30 days, so a daily refresh only probes new
domains. It sends one request per domain to the startup's own homepage and
nothing else.

## Tech picks

`tech_picks.md` narrows the 5,449 down to 70 companies whose *product* is
technical rather than merely software-delivered, in five themes: AI, developer
tools and infrastructure, hard tech, security, and bio. Selection is by YC's own
tags plus product wording, with a penalty for consumer companies that happen to
carry an AI tag. Tune the themes in `tools/pick_tech.py`; nothing is hand-picked.

## The website

`docs/` is a single static page — inline CSS, a little vanilla JS for the filter
box, no dependencies. GitHub Pages serves it from the `main` branch's `/docs`
folder, so pushing the repo is the whole deploy.

## Fields that matter

**What they sell**

- `product` — the one-liner. This is the company's own pitch, not a summary.
- `product_detail` — the long description, whitespace-normalised and otherwise
  untouched. Where the real substance is.
- `industries`, `tags`, `industry`, `subindustry` — YC's own taxonomy.
- `description_source` — which of the above the `product` text came from, so
  you can tell a real pitch from a fallback.

**When**

- `batch`, `batch_year`, `years_since_batch`.
- `batch_year` is the YC batch year, used as a **proxy** for founding year.
  It is usually the same year or one after incorporation, occasionally two. Do
  not cite it as a founding date.
- `recent_10y`, `recent_5y` — precomputed against the build year, so filtering
  does not require date arithmetic.

**Where**

- `hq_city`, `hq_country` parsed from the first non-remote location string.
- `regions` — the full upstream list, unfiltered. Always trust this over
  `market` when you need completeness.
- `market` — one of `India`, `United States`, `Europe`, or `""`. Priority is
  India, then United States, then Europe, so a company with offices in both
  the US and Europe reads as `United States` here while `regions` still shows
  both. Europe means the EU plus UK, EEA, Switzerland and the western Balkans;
  Russia, Belarus, Turkey and Israel are excluded on purpose.

**Whether it still exists**

- `status` — YC's raw value: `Active`, `Inactive`, `Acquired`, `Public`.
- `outcome` — normalised to `operating`, `inactive`, `acquired`, `public`.
- `site_state` — `live`, `blocked`, `gone` (404/410), `server_error`,
  `error`, `unreachable`, or empty if never checked.
- `likely_defunct` — true when YC marks it Inactive **or** the website is gone
  or unreachable. An independent check, not a certainty.
- `status_note` — one readable line combining all of the above, e.g.
  *"Acquired by Farfetch in 2021"* or *"Inactive on YC (delisted or wound
  down); website unreachable"*.
- `acquired_by`, `exit_year`, `exit_source`, `exit_evidence` — parsed from the
  description. `exit_source` is `yc_status` when YC itself marks the company
  acquired, and `description` when the only evidence is text. `exit_evidence`
  is the sentence it came from, so you can check the parse. 57 of 840 acquired
  companies name their acquirer; the rest just say "acquired".

## Known noise

- `Inactive` on YC means the profile was delisted, which usually but not always
  means the company wound down.
- `blocked` means the site refused our request, not that it is dead.
- A parked domain often answers `200`, so `site_state: live` is not proof of
  life. The reverse error is rarer but real.
- 32 of the 5,449 recent rows have no description at all, and 430 across the
  full corpus have only a fallback line. Filter on `product_detail != ""`.
- Three rows are marked Active but carry an acquisition sentence; those are
  founder bios in the description ("acquired by Dropbox") rather than exits.
  `exit_source: description` flags them.

## Next sources, when the US skew becomes a problem

Accelerator and VC portfolio pages fill India and Europe far better than more
YC rows would: Antler, Entrepreneur First, Station F, Techstars, 500 Global,
Peak XV, Accel, Blume, Lightspeed India, Balderton, Seedcamp. Each needs its
own parser; each gives name, one-liner and country. HN "Launch HN" posts
(Algolia API, no key) add founder-written origin stories, which is where the
motivation material actually lives.
