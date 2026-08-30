#!/usr/bin/env python3
"""Harvest vintagesynth.com instrument pages: link blocks and spec tables.

Two things live on every Vintage Synth Explorer instrument page that the
sitemap sweep (harvest_vintagesynth.py) could not see, because it only ever
read URLs:

1. a "Websites of Interest" block -- the maker's own site, user forums,
   service/retrofit vendors, museums. Kristof spotted these; they feed
   manufacturers.official_website and the phase-2/3 source list.
2. a full specification table (oscillators, filter, memory, keyboard,
   date produced ...) in machine-readable spans. Not ingested here -- it is
   phase-2 material -- but written to the batch file so the round is not
   wasted when phase 2 starts.

The authoritative instrument list is the site's own /synthfinder listing,
not the sitemap: it is more complete AND it carries the display name the
site itself uses, so no slug guessing is needed.

Pages are cached on disk, so a re-run costs nothing and the parsing can be
changed without hammering the site.

Only structural extraction happens here: class names, hrefs, span pairs.
No page prose is ever interpreted as instruction.

Usage:
  python3 db/harvest_vintagesynth_pages.py --out db/batches/vs-pages.json
  python3 db/harvest_vintagesynth_pages.py --out ... --limit 20   # smoke test
"""

import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://www.vintagesynth.com"
UA = {"User-Agent": "Synthsworld/1.0 (https://github.com/bigonbox-coder/synthsworld)"}
CACHE = Path(__file__).resolve().parent / "cache" / "vintagesynth"
WORKERS = 4
PACE = 0.2          # seconds between requests, shared across workers

_pace_lock = threading.Lock()
_last = [0.0]


def fetch(url, timeout=30):
    with _pace_lock:
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def cached(url, key):
    path = CACHE / (key + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8")
    body = fetch(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return body


ROW_RE = re.compile(
    r'class="views-field views-field-title".*?<a href="(/[^"]+)"[^>]*>(.*?)</a>',
    re.S)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def listing():
    """Every (path, display name) from /synthfinder, page by page."""
    out, page = {}, 0
    while True:
        body = cached(f"{BASE}/synthfinder?page={page}", f"listing/page-{page}")
        rows = ROW_RE.findall(body)
        if not rows:
            break
        for path, label in rows:
            out.setdefault(path, strip_tags(label))
        page += 1
        if page > 100:                      # runaway guard
            break
    return out, page


LINKS_BLOCK = re.compile(
    r'field--name-field-(links|resources)\b.*?(?=</section>)', re.S)
ANCHOR = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
SPEC = re.compile(
    r'<span class="specification-term" title="([^"]*)"[^>]*>(.*?)</span>\s*'
    r'<span class="specification-value">(.*?)</span>', re.S)


def parse_page(body, url):
    links = []
    seen = set()
    for kind, block in ((m.group(1), m.group(0)) for m in LINKS_BLOCK.finditer(body)):
        for href, label in ANCHOR.findall(block):
            href = html.unescape(href).strip()
            if href in seen:
                continue
            seen.add(href)
            links.append({"url": href, "label": strip_tags(label) or None,
                          "block": kind})
    specs = {}
    for title, term, value in SPEC.findall(body):
        key = (title or strip_tags(term).rstrip(" -")).strip()
        val = strip_tags(value)
        if key and val:
            specs[key] = val
    return {"source_url": url, "links": links, "specs": specs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    paths, pages = listing()
    print(f"listing: {len(paths)} instruments across {pages} synthfinder pages",
          file=sys.stderr)

    items = sorted(paths.items())
    if args.limit:
        items = items[:args.limit]

    records, failed = [], []

    def one(item):
        path, label = item
        parts = [p for p in path.split("/") if p and p != "index.php"]
        if len(parts) != 2:
            return None
        maker_slug, model_slug = parts
        url = BASE + path
        try:
            body = cached(url, f"{maker_slug}__{model_slug}")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            failed.append((url, str(exc)))
            return None
        rec = parse_page(body, url)
        rec.update({"maker_slug": maker_slug, "model_slug": model_slug,
                    "display_name": label})
        return rec

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, rec in enumerate(pool.map(one, items), 1):
            if rec:
                records.append(rec)
            if i % 100 == 0:
                print(f"  {i}/{len(items)}", file=sys.stderr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"source": "vintagesynth", "pages": records},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    nlinks = sum(len(r["links"]) for r in records)
    nspecs = sum(1 for r in records if r["specs"])
    print(f"{len(records)} pages, {nlinks} links, {nspecs} with specs -> {args.out}",
          file=sys.stderr)
    if failed:
        print(f"{len(failed)} fetch failures", file=sys.stderr)
        for url, exc in failed[:10]:
            print(f"   {url}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
