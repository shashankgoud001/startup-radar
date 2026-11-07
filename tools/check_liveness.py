"""Check whether each company's website is still alive.

YC's own `status` is a curation signal, not a death certificate: a company can
be marked Active while its site has been parked for years, or Inactive while
the site still runs. One HEAD request per domain gives an independent signal.

Results are cached in data/raw/liveness.json so re-runs only probe new or stale
domains. This is a heuristic: 403 means "blocked us", not "dead", and a parked
domain usually answers 200 with an empty page.
"""

import json
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "yc_companies.json"
CORPUS_PATH = ROOT / "data" / "startups.json"
CACHE_PATH = ROOT / "data" / "raw" / "liveness.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; startup-radar/1.0; "
    "personal research, one request per domain)"
)
TIMEOUT = 8
DEFAULT_WORKERS = 32

#: How long a cached result is trusted before the domain is probed again.
CACHE_DAYS = 30

#: Statuses that mean "this server does not do HEAD", so retry with GET.
RETRY_WITH_GET = {400, 403, 405, 406, 501}


def domain_of(url: str) -> str:
    match = url.split("://", 1)[-1] if "://" in url else url
    host = match.split("/")[0].split("?")[0].split("#")[0].lower()
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def classify(code) -> str:
    if isinstance(code, int):
        if code < 400:
            return "live"
        if code in (404, 410):
            return "gone"
        if code in (401, 403, 429):
            return "blocked"
        if code >= 500:
            return "server_error"
        return "error"
    return "unreachable"


def probe(url: str) -> dict:
    """One request, HEAD first, GET as a fallback. Never raises."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    result = {"state": "unreachable", "status": None, "final_url": "", "error": ""}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(
            url, method=method, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
                result.update(
                    status=response.status,
                    state=classify(response.status),
                    final_url=response.geturl(),
                )
                return result
        except urllib.error.HTTPError as error:
            result.update(
                status=error.code,
                state=classify(error.code),
                final_url=getattr(error, "url", url),
            )
            if method == "HEAD" and error.code in RETRY_WITH_GET:
                continue
            return result
        except Exception as error:  # DNS, TLS, timeout, connection reset
            result["error"] = type(error).__name__
            if method == "HEAD" and result["error"] in {"RemoteDisconnected", "ConnectionResetError"}:
                continue
            return result
    return result


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return data.get("domains", data)


def is_fresh(entry: dict, days: int = CACHE_DAYS) -> bool:
    checked = entry.get("checked_at") or ""
    try:
        when = datetime.fromisoformat(checked)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc) - when < timedelta(days=days)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    limit = None
    workers = DEFAULT_WORKERS
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    if "--workers" in argv:
        workers = int(argv[argv.index("--workers") + 1])

    path = CORPUS_PATH if CORPUS_PATH.exists() else RAW_PATH
    if not path.exists():
        print(f"missing {path}; run tools/fetch_yc.py first", file=sys.stderr)
        return 1

    records = json.loads(path.read_text(encoding="utf-8"))
    urls = {}
    for record in records:
        url = (record.get("website") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            if not url:
                continue
            url = "https://" + url
        domain = domain_of(url)
        if domain and domain not in urls:
            urls[domain] = url

    cache = load_cache()
    todo = [
        (domain, url)
        for domain, url in urls.items()
        if not is_fresh(cache.get(domain) or {})
    ]
    if limit:
        todo = todo[:limit]

    print(
        f"{len(urls)} domains, {len(urls) - len(todo)} cached, probing {len(todo)}",
        file=sys.stderr,
    )

    checked_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe, url): (domain, url) for domain, url in todo}
        for done, future in enumerate(futures, start=1):
            entry = future.result()
            entry["checked_at"] = checked_at
            entry["url"] = futures[future][1]
            cache[futures[future][0]] = entry
            if done % 250 == 0 or done == len(futures):
                print(f"  {done}/{len(futures)}", file=sys.stderr)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "checked_at": checked_at,
                "domains": dict(sorted(cache.items())),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    from collections import Counter

    counts = Counter(entry.get("state") for entry in cache.values())
    print(f"wrote {CACHE_PATH}: {dict(counts.most_common())}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
