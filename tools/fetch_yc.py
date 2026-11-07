"""Download the YC company dump once and cache it under data/raw/.

Source: https://yc-oss.github.io/api/companies/all.json - an unofficial mirror
that rebuilds daily from Y Combinator's public search index. One GET, no auth,
no pagination, so there is nothing to be polite about beyond not re-fetching
what we already have.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

SOURCE_URL = "https://yc-oss.github.io/api/companies/all.json"

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "yc_companies.json"

#: Re-download when the cache is older than this. The upstream rebuilds daily.
MAX_AGE_SECONDS = 24 * 60 * 60

USER_AGENT = "startup-radar/1.0 (personal research; caches one public JSON)"


def is_fresh(path: Path, max_age: int = MAX_AGE_SECONDS) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < max_age


def download(dest: Path = RAW_PATH, force: bool = False) -> Path:
    """Fetch the dump to `dest` unless a fresh copy is already there."""
    if not force and is_fresh(dest):
        print(f"{dest} is fresh, skipping download", file=sys.stderr)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()

    # Parse before writing so a truncated or error page never lands on disk.
    companies = json.loads(payload)
    if not isinstance(companies, list) or not companies:
        raise ValueError(f"unexpected payload from {SOURCE_URL}")

    dest.write_bytes(payload)
    print(
        f"wrote {dest} ({len(companies)} companies, {len(payload)} bytes)",
        file=sys.stderr,
    )
    return dest


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    download(force="--force" in argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
