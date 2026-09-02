#!/usr/bin/env python3
"""reverb.com: gyartonevek a varolistara a NYILVANOS API-bol.

Kristof adta a forrast 2026-09-02, es a merest latva engedelyezte az 5-os
kuszobot: "Ok mehet."

MIERT AZ API ES NEM AZ OLDAL
============================
A reverb.com HTML fooldala 403-at ad nekunk. Van viszont nyilvanos API, ami
TOKEN NELKUL valaszol, es a robots.txt nem tiltja:

    https://api.reverb.com/api/listings?product_type=keyboards-and-synths
        &category=analog-synths        (Accept-Version: 3.0 fejleccel)

Tehat nem kaparjuk az oldalt, hanem a sajat API-jukat kerdezzuk, ahogy szantak.

MIT AD ES MIT NEM
=================
A make es a model mezot az ELADO gepeli be, nem a Reverb. Ezert ez FELFEDEZESI
forras: nevek, amiknek utana kell nezni. NEM teny-forras, es nem is ir
hangszert a tablaba. Csak a discovery_queue-ba tesz nevet.

A KUSZOB, MERESSEL
==================
Meres a teljes kategorian (2026-09-02, 7725 hirdetes, 729 kulonbozo nev), a
zarojelben a nekunk uj nev:

    1+ hirdetes  729 (521)      5+ hirdetes  143 (52)
    2+ hirdetes  309 (158)     10+ hirdetes   74 (16)
    3+ hirdetes  229 (107)     20+ hirdetes   43 (7)

Egy hirdetesnel a lista tobbsege elgepeles vagy eladoi szoveg. Ot hirdetesnel
mar valodi gyartok allnak: UDO Audio, SOMA, Macbeth, Oxford Synthesizer
Company, PWM, Elta Music, Cre8Audio, Serge, Blacet Research, Tasty Chips,
Synth-Werk. Ezert lett 5 a kuszob.

A JUNK lista nem izles kerdese: ezek nem gyartonevek, hanem eladoi kenyelem
("Unknown", "DIY", "OEM"), vagy alkatresz-beszallito (Pratt Read billentyuzet).

Hasznalat:
    python3 db/harvest_reverb.py --dry-run
    python3 db/harvest_reverb.py --ingest
    python3 db/harvest_reverb.py --dry-run --cache sweep.json   # meglevo meresbol
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from maker_lookup import MakerLookup  # noqa: E402

DB = HERE / "synthsworld.sqlite"
API = ("https://api.reverb.com/api/listings?product_type=keyboards-and-synths"
       "&category=analog-synths&per_page=50&page={page}")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
THRESHOLD = 5
DELAY = 1.2

# Nem gyartonev, hanem eladoi kenyelem vagy alkatresz-beszallito.
JUNK = {"unknown", "diy", "oem", "unbranded", "ussr", "raresynthparts",
        "various", "various brand", "n/a", "none", "homemade", "custom",
        "vintage", "other", "no brand", "pratt read"}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get(url):
    r = subprocess.run(["curl", "-sS", "--max-time", "30", "-A", UA,
                        "-H", "Accept-Version: 3.0", url], capture_output=True)
    try:
        return json.loads(r.stdout or b"{}")
    except json.JSONDecodeError:
        return {}


def sweep(max_pages=200):
    """-> Counter(make -> hany hirdetesben)"""
    makes = Counter()
    seen = 0
    for page in range(1, max_pages + 1):
        d = get(API.format(page=page))
        rows = d.get("listings") or []
        if not rows:
            break
        for row in rows:
            seen += 1
            name = (row.get("make") or "").strip()
            if name:
                makes[name] += 1
        if page % 20 == 0:
            print(f"  {page}. oldal, {seen} hirdetes", flush=True)
        time.sleep(DELAY)
    print(f"{seen} hirdetes, {len(makes)} kulonbozo gyarto-nev")
    return makes


def looks_like_seller_text(name):
    """Az eladok neha egesz mondatot irnak a gyarto mezobe."""
    return (len(name) > 40 or "|" in name or " and more" in name.lower()
            or re.search(r"\d{2,}\s?(x|\")", name.lower()) is not None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--cache", help="korabbi meres JSON-ja (makes: [[nev, db], ...])")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    if not (args.ingest or args.dry_run):
        ap.print_help()
        return 0

    if args.cache:
        makes = Counter(dict(json.loads(Path(args.cache).read_text())["makes"]))
        print(f"meres a cache-bol: {len(makes)} nev")
    else:
        makes = sweep()
    if not makes:
        print("! nem jott adat az API-bol")
        return 1

    con = sqlite3.connect(args.db)
    lookup = MakerLookup(con)
    in_queue = {r[0].strip().lower() for r in con.execute(
        "SELECT manufacturer_name FROM discovery_queue")}

    take, junk, known, queued, thin = [], [], [], [], []
    for name, count in makes.most_common():
        if count < args.threshold:
            thin.append(name)
        elif name.strip().lower() in JUNK or looks_like_seller_text(name):
            junk.append(name)
        elif lookup.find(name):
            known.append(name)
        elif name.strip().lower() in in_queue:
            queued.append(name)
        else:
            take.append((name, count))

    print(f"\nkuszob: {args.threshold}+ hirdetes")
    print(f"  {len(thin):4d} nev a kuszob alatt, kihagyva")
    print(f"  {len(junk):4d} nem gyartonev (eladoi szoveg vagy beszallito): {', '.join(junk)}")
    print(f"  {len(known):4d} mar a tablankban")
    print(f"  {len(queued):4d} mar a varolistan")
    print(f"  {len(take):4d} UJ nev a varolistara:")
    for name, count in take:
        print(f"       {count:4d}  {name}")

    if not args.ingest:
        print("\n-- szarazfutas, semmi nem irodott. --ingest kell hozza --")
        return 0

    ts = now_iso()
    for name, count in take:
        note = (f"reverb.com API, {ts[:10]}, {count} hirdetes az Analog Synths "
                f"kategoriaban. FELFEDEZESI forras: a nevet az elado gepelte be, "
                f"tehat a scope-teszt (hangkelto-e, fizikai eszkoz-e) ELOTTE all.")
        con.execute("INSERT INTO discovery_queue (manufacturer_name, status, notes) "
                    "VALUES (?, 'found', ?)", (name, note))
    con.execute("UPDATE source_domains SET harvester='harvest_reverb', harvested_at=? "
                "WHERE domain='reverb.com'", (ts,))
    con.commit()
    print(f"\nbeirva: {len(take)} uj varolistas nev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
