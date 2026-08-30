#!/usr/bin/env python3
"""Seed `discovery_queue` from Wikipedia's manufacturer categories.

Why: until now the queue only grew from manual seeding and from relations that
happened to surface during research, so which manufacturers exist at all was
limited by what we already knew. Wikipedia maintains curated category trees of
synthesizer and electronic-instrument makers, including per-country
subcategories -- a far better starting list than guessing names, and free.

This only adds NAMES to the queue. It never writes to `manufacturers`: a name
here has had no research behind it, and the project's rule is that a record
must not exist as if it were researched when it is not.

Category titles are text other people can edit, so they are treated as data:
sanitised, length-capped, and filtered to article-namespace pages before
anything is written.

Usage:
    python3 db/seed_from_wikipedia.py [--wiki en] [--dry-run]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
# Wikimedia rate-limits anonymous clients whose User-Agent carries no way to
# contact the operator; without the project URL here the API answers 429
# regardless of how slowly requests are paced.
UA = "SynthsworldResearchBot/1.0 (https://synthsworld.com)"
# The API returns 429 quickly on back-to-back calls, and a 429 looks exactly
# like an empty category -- which silently under-seeds instead of failing.
PAUSE_SECONDS = 1.5

# Roots to walk. Subcategories are followed one level down, which is where the
# per-country lists live ("... companies of Japan").
ROOTS = [
    "Category:Synthesizer manufacturing companies",
    "Category:Electronic musical instrument manufacturing companies",
    "Category:Drum machine manufacturers",
    "Category:Organ manufacturing companies",
]

# Pages that are not a company: navigation, lists, disambiguation, and the
# instrument articles that sit in the same trees.
SKIP_PATTERNS = [
    re.compile(r"^List of ", re.I),
    re.compile(r"\(disambiguation\)$", re.I),
    re.compile(r"^Comparison of ", re.I),
    # "Serge synthesizer" is an article about the instrument, not the company;
    # the company already exists under its real name.
    re.compile(r"\bsynthesi[sz]ers?$", re.I),
]
MAX_NAME = 120

# Dropped when comparing a harvested name against what we already have, so
# "Oberheim Electronics" does not get queued next to the existing "Oberheim".
# Comparison only -- the harvested spelling is what gets stored.
NOISE_WORDS = {
    "inc", "incorporated", "ltd", "limited", "llc", "gmbh", "ag", "ab", "kg",
    "co", "company", "corp", "corporation", "spa", "srl", "sa", "bv", "nv",
    "plc", "oy", "as", "electronics", "electronic", "instruments", "instrument",
    "music", "musical", "audio", "systems", "system", "digital", "sound",
    "technologies", "technology", "int", "international",
}


def api(wiki, params):
    time.sleep(PAUSE_SECONDS)
    params = {**params, "format": "json"}
    url = f"https://{wiki}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry and move on
            if attempt == 2:
                raise RuntimeError(f"wikipedia api failed: {exc}") from exc
            time.sleep(5 * (attempt + 1))
    return {}


def members(wiki, title, kind):
    """Category members of one namespace kind: 'page' or 'subcat'."""
    out, cont = [], None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": title,
            "cmlimit": "500",
            "cmtype": kind,
        }
        if cont:
            params["cmcontinue"] = cont
        data = api(wiki, params)
        out += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            return out


def clean(title):
    """Sanitise an externally-edited title into a plain company name, or None."""
    name = re.sub(r"\s*\(.*?\)\s*$", "", title).strip()  # drop "(company)" suffixes
    name = "".join(ch for ch in name if ch.isprintable())
    name = " ".join(name.split())
    if not name or len(name) > MAX_NAME:
        return None
    if any(p.search(name) for p in SKIP_PATTERNS):
        return None
    return name


def compare_key(name):
    """Loose identity key: lowercase, punctuation-free, corporate noise dropped."""
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    core = [w for w in words if w not in NOISE_WORDS]
    return " ".join(core or words)


def existing_names(conn):
    """Every name already known, in any form, as loose comparison keys."""
    seen = set()
    for q in (
        "SELECT canonical_name FROM manufacturers",
        "SELECT name FROM manufacturer_name_history",
        "SELECT manufacturer_name FROM discovery_queue",
    ):
        seen |= {compare_key(r[0]) for r in conn.execute(q) if r[0]}
    return seen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wiki", default="en", help="wiki language code (default: en)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    harvested = {}  # name -> source category
    for root in ROOTS:
        pages = members(args.wiki, root, "page")
        subcats = members(args.wiki, root, "subcat")
        if not pages and not subcats:
            print(f"  (skipped, no such category: {root})")
            continue
        print(f"  {root}: {len(pages)} pages, {len(subcats)} subcategories")
        for title in pages:
            name = clean(title)
            if name:
                harvested.setdefault(name, root)
        for sub in subcats:
            for title in members(args.wiki, sub, "page"):
                name = clean(title)
                if name:
                    harvested.setdefault(name, sub)

    conn = sqlite3.connect(str(DB_PATH))
    known = existing_names(conn)
    new, dupes = {}, []
    for n, c in harvested.items():
        (dupes.append(n) if compare_key(n) in known else new.update({n: c}))

    print(f"\nharvested {len(harvested)} names, {len(new)} new, {len(dupes)} already known")
    if args.dry_run:
        for n in sorted(new):
            print("  +", n)
        print("\n-- dry run, nothing written --")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for name, cat in sorted(new.items()):
        conn.execute(
            """INSERT INTO discovery_queue
               (manufacturer_name, status, notes, created_at, updated_at)
               VALUES (?, 'found', ?, ?, ?)""",
            (name, f"seeded from {args.wiki}.wikipedia {cat}", ts, ts),
        )
    conn.commit()
    print(f"inserted {len(new)} new queue rows")


if __name__ == "__main__":
    main()
