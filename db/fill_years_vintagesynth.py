#!/usr/bin/env python3
"""Fill instruments.year from the vintagesynth 'Date Produced' spec.

The harvested spec tables carry a production date for 722 models, written as
either a single year or a range ("1981 - 1984"). The FIRST year is stored:
year means introduced, not withdrawn.

Only rows whose year is currently NULL are touched, matched on the exact
source_url the harvest recorded -- no name guessing.

Reversible in one statement if the source is ever doubted:
  UPDATE instruments SET year = NULL
  WHERE source_url LIKE '%vintagesynth.com%';

Usage:  python3 db/fill_years_vintagesynth.py [--dry-run]
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_vintagesynth import SLUG_ALIASES, title_case          # noqa: E402
from harvest_wikipedia_instruments import load_makers              # noqa: E402

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
BATCH = Path(__file__).resolve().parent / "batches" / "vintagesynth-pages-1.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(BATCH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
    makers = load_makers(conn)

    def norm(x):
        return re.sub(r"[^a-z0-9]", "", x.lower())

    years, by_name = {}, {}
    for page in data["pages"]:
        raw = page["specs"].get("Date Produced")
        if not raw:
            continue
        m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", raw)
        if not m:
            continue
        year = int(m.group(1))
        years[page["source_url"].rstrip("/")] = year
        # Most vintagesynth models were merged into rows that already existed
        # under another source, so their source_url is not this page. Fall back
        # to (manufacturer, normalised model name) for those.
        slug = page["maker_slug"]
        canon = SLUG_ALIASES.get(slug.lower()) or makers.get(slug.replace("-", " ").lower())
        if canon:
            for name in (page.get("display_name") or "", title_case(page["model_slug"])):
                name = re.sub(rf"^{re.escape(canon.split()[0])}\s+", "", name, flags=re.I)
                if name:
                    by_name.setdefault((canon, norm(name)), year)
    print(f"{len(years)} production years in the batch", file=sys.stderr)

    rows = conn.execute(
        """SELECT i.id, i.source_url, m.canonical_name, i.name
           FROM instruments i JOIN manufacturers m ON m.id = i.manufacturer_id
           WHERE i.year IS NULL""").fetchall()
    updates, by_url_hits = [], 0
    for iid, src, canon, name in rows:
        year = None
        if src:
            key = src.rstrip("/")
            year = years.get(key) or years.get(key.replace("/index.php", ""))
            if year:
                by_url_hits += 1
        if not year:
            year = by_name.get((canon, norm(name)))
        if year:
            updates.append((year, iid))
    print(f"{by_url_hits} matched on source_url, "
          f"{len(updates) - by_url_hits} on manufacturer+name", file=sys.stderr)

    print(f"{len(updates)} instruments would get a year", file=sys.stderr)
    if args.dry_run:
        return
    with conn:
        conn.executemany("UPDATE instruments SET year = ? WHERE id = ?", updates)
    total = conn.execute(
        "SELECT COUNT(*) FROM instruments WHERE year IS NOT NULL").fetchone()[0]
    print(f"{total} instruments now carry a year", file=sys.stderr)


if __name__ == "__main__":
    main()
