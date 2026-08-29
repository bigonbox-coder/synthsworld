#!/usr/bin/env python3
"""Seed discovery_queue with the initial phase-1 test batch.
Safe to re-run: manufacturer_name is UNIQUE, duplicates are ignored.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"

SEED_NAMES = [
    "Moog",
    "Roland",
    "Korg",
    "Sequential",
    "Yamaha",
    "Oberheim",
    "ARP Instruments",
    "Elektron",
]

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    for name in SEED_NAMES:
        conn.execute(
            "INSERT OR IGNORE INTO discovery_queue (manufacturer_name) VALUES (?)",
            (name,),
        )
    conn.commit()
    rows = conn.execute("SELECT manufacturer_name, status FROM discovery_queue").fetchall()
    conn.close()
    print(f"discovery_queue now has {len(rows)} rows:")
    for name, status in rows:
        print(f"  - {name} [{status}]")
