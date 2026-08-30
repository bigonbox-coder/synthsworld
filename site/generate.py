#!/usr/bin/env python3
"""Regenerate the Synthsworld static viewer site from synthsworld.sqlite.

Re-runnable any time the DB changes: reads the manufacturers table (plus
name history and relations), and writes data/manufacturers.json. The HTML/
CSS/JS shell (index.html, style.css, app.js) are static and not touched by
this script -- only the data file is regenerated.

Usage: python3 generate.py
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent / "db" / "synthsworld.sqlite"
OUT_PATH = ROOT / "data" / "manufacturers.json"


def main() -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, canonical_name, country, city, founded_year, ended_year,
               founders, short_history, long_history,
               official_website, status, confidence_level
        FROM manufacturers
        ORDER BY canonical_name COLLATE NOCASE
        """
    )
    manufacturers = [dict(row) for row in cur.fetchall()]

    by_id = {m["id"]: m for m in manufacturers}
    for m in manufacturers:
        m["name_history"] = []
        m["relations"] = []

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

    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(manufacturers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(manufacturers)} manufacturers to {OUT_PATH}")


if __name__ == "__main__":
    main()
