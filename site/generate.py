#!/usr/bin/env python3
"""Regenerate the Synthsworld static viewer site from synthsworld.sqlite.

Re-runnable any time the DB changes: reads the manufacturers table (plus
name history and relations), and writes data/manufacturers.json. The HTML/
CSS/JS shell (index.html, style.css, app.js) are static and not touched by
this script -- only the data file is regenerated.

Usage: python3 generate.py
"""
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent / "db" / "synthsworld.sqlite"
OUT_PATH = ROOT / "data" / "manufacturers.json"
# Master logo assets live in Drive; the admin app keeps a local copy for its
# thumbnails, and the public site needs its own copy because it is a plain
# static upload with no access to either.
LOGO_SRC_DIR = ROOT.parent / "admin" / "static" / "logos"
LOGO_OUT_DIR = ROOT / "logos"


def collect_logos(cur, by_id):
    """Copy each manufacturer's logo files into site/logos/ and record them.

    Kristóf's rule (2026-08-30): keep the genuinely defining variants in the
    database, but at least one has to actually reach the public site. Only
    rows whose file exists locally are published -- a row with no file means
    "searched, found nothing" and has nothing to show.
    """
    LOGO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in LOGO_OUT_DIR.glob("logo-*"):
        old.unlink()          # rebuilt from scratch, so a deleted logo really goes
    published = 0
    for row in cur.execute(
        """SELECT id, manufacturer_id, start_year, end_year, source_url,
                  logo_review_status
           FROM manufacturer_logos
           -- Kristóf's approved logo is the one that represents the company,
           -- so it leads; an 'outdated' mark is real history but must never be
           -- the hero image; era ordering breaks the remaining ties.
           -- CASE, not two boolean keys: logo_review_status is NULL for an
           -- unreviewed logo, and in SQLite `NULL = 'approved'` is NULL, which
           -- sorts FIRST -- so a boolean ordering would put an unreviewed
           -- upload ahead of the approved mark, exactly backwards.
           ORDER BY CASE logo_review_status
                      WHEN 'approved' THEN 0 WHEN 'outdated' THEN 2 ELSE 1 END,
                    end_year IS NULL DESC, start_year IS NULL, start_year DESC, id DESC"""
    ):
        m = by_id.get(row["manufacturer_id"])
        if m is None:
            continue
        # svg, png, jpg, jpeg -- ugyanaz a lista, mint az admin
        # logo_rel_path()-jaban; a ketto nem terhet el, kulonben a panelen
        # latszo logo nem kerul ki a publikus oldalra.
        src = next((LOGO_SRC_DIR / f"logo-{row['id']}.{ext}"
                    for ext in ("svg", "png", "jpg", "jpeg")
                    if (LOGO_SRC_DIR / f"logo-{row['id']}.{ext}").exists()), None)
        if src is None:
            continue
        shutil.copy(src, LOGO_OUT_DIR / src.name)
        m["logos"].append({
            "file": f"logos/{src.name}",
            "start_year": row["start_year"],
            "end_year": row["end_year"],
            "source_url": row["source_url"],
            "review_status": row["logo_review_status"],
        })
        published += 1
    return published


def main() -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, canonical_name, long_name, country, city, founded_year, ended_year,
               founders, short_history, long_history,
               official_website, status, confidence_level, entity_type
        FROM manufacturers
        ORDER BY canonical_name COLLATE NOCASE
        """
    )
    manufacturers = [dict(row) for row in cur.fetchall()]

    by_id = {m["id"]: m for m in manufacturers}
    for m in manufacturers:
        m["name_history"] = []
        m["relations"] = []
        m["instruments"] = []
        m["logos"] = []

    cur.execute(
        """
        SELECT manufacturer_id, name, start_year, end_year
        FROM manufacturer_name_history
        ORDER BY start_year
        """
    )
    for row in cur.fetchall():
        m = by_id.get(row["manufacturer_id"])
        if m is not None:
            m["name_history"].append(
                {"name": row["name"], "start_year": row["start_year"], "end_year": row["end_year"]}
            )

    cur.execute(
        """
        SELECT manufacturer_id, name, year, category
        FROM instruments
        ORDER BY year IS NULL, year, name COLLATE NOCASE
        """
    )
    for row in cur.fetchall():
        m = by_id.get(row["manufacturer_id"])
        if m is not None:
            m["instruments"].append(
                {"name": row["name"], "year": row["year"], "category": row["category"]}
            )

    cur.execute(
        """
        SELECT manufacturer_id, related_manufacturer_id, relation_type, year
        FROM manufacturer_relations
        ORDER BY year
        """
    )
    for row in cur.fetchall():
        m = by_id.get(row["manufacturer_id"])
        related = by_id.get(row["related_manufacturer_id"])
        if m is not None:
            m["relations"].append(
                {
                    "relation_type": row["relation_type"],
                    "year": row["year"],
                    "related_manufacturer_id": row["related_manufacturer_id"],
                    "related_name": related["canonical_name"] if related else None,
                }
            )

    logo_count = collect_logos(cur, by_id)

    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(manufacturers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(manufacturers)} manufacturers to {OUT_PATH}")
    print(f"Published {logo_count} logo files to {LOGO_OUT_DIR}")


if __name__ == "__main__":
    main()
