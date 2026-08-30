#!/usr/bin/env python3
"""Harvest Roland's own Updates & Drivers index.

https://www.roland.com/us/support/updates_drivers/ is server-rendered and
links to a downloads page for every product Roland still supports -- 567 of
them, shaped /us/support/by_product/<slug>/updates_drivers/. robots.txt
disallows /support/ and /<region>/support/knowledge_base/, but NOT this path.

This is the manufacturer's own site, so anything behind these links is
top-tier: firmware, drivers and manuals straight from the maker. It is
therefore the natural entry point for phase 3 (documents), which has no table
yet -- so this pass stops at recording the per-product support URL as an
official link on the instrument we already hold.

It deliberately does NOT create instruments from the unmatched slugs. Roland's
catalogue here is mostly out of scope: MIDI keyboard controllers, wind
instruments, audio players, video switchers. Adding them wholesale would repeat
the category mistake -- a list is not evidence of what something is.

Usage:
  python3 db/harvest_roland_support.py --out db/batches/roland-support.json
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

INDEX = "https://www.roland.com/us/support/updates_drivers/"
BASE = "https://www.roland.com"
MAKER = "Roland Corporation"
DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept-Language": "en-US,en;q=0.9"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    page = urllib.request.urlopen(
        urllib.request.Request(INDEX, headers=UA), timeout=45
    ).read().decode("utf-8", "replace")
    slugs = sorted(set(re.findall(
        r"/us/support/by_product/([^/\"']+)/updates_drivers/", page)))
    print(f"{len(slugs)} products in Roland's own support index", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id FROM manufacturers WHERE canonical_name = ?", (MAKER,)).fetchone()
    if not row:
        sys.exit(f"{MAKER} is not in the database")
    mid = row[0]
    held = {norm(n): n for (n,) in conn.execute(
        "SELECT name FROM instruments WHERE manufacturer_id = ?", (mid,))}

    pages, unmatched = [], []
    for slug in slugs:
        name = held.get(norm(slug))
        if not name:
            unmatched.append(slug)
            continue
        url = f"{BASE}/us/support/by_product/{slug}/updates_drivers/"
        pages.append({
            "maker_slug": MAKER, "model_slug": name, "display_name": name,
            "source_url": INDEX,
            "links": [{"url": url, "label": f"{name} updates & drivers (Roland)",
                       "block": "links"}],
            "specs": {},
        })

    Path(args.out).write_text(
        json.dumps({"source": "roland-support", "pages": pages,
                    "unmatched_slugs": unmatched}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"{len(pages)} matched to instruments we hold, "
          f"{len(unmatched)} slugs left unmatched (kept in the file, not queued)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
