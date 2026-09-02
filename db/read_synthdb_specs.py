#!/usr/bin/env python3
"""synth-db oldal-cache kiolvasasa MODELL NELKUL: evszam, kategoria, technologia.

Kristof, 2026-09-02: "Az ingyenes kiolvaso mehet, ne feledd az adminoldalt is
frissiteni. A halott forrast ugyanugy, mint a rovid gyartoval."

MIERT INGYENES
==============
A processing_backlog synthdb_page_readout job kb. 2,4 millio tokenre volt
becsulve, mert azt hittuk hogy az evszam es a kategoria csak a leiras
prozajaban van. Nincs igy: az oldalak aljan strukturalt adattablazat all.

    Brand / Elektronika        Device / Synth
    Model / EM-26              Engine Type / Analog
                               Produced: / 1992 - 1992

Cimke-sor, alatta ertek-sor. Ezt parser szedi ki, nem modell. Meres
(2026-09-02, mind az 1903 cache-elt oldalon): 1611 oldalon megvan a Device es
az evszam is, ez 85%. Ahol nincs, ott az oldalon MAGA A MEZO ures, tehat
modell sem tudna kitalalni.

MIT IR ES MIT NEM
=================
- Csak azokat a hangszereket erinti, amiknek a source_url-je synth-db.com ES
  szerepel a cache-ben.
- Csak URES mezot tolt ki (year IS NULL, category IS NULL, technology 'unknown'
  vagy NULL). Meglevo erteket SOHA nem ir felul: ott mas forras, esetleg ember
  dontott, es egy tomeges import nem irhatja felul.
- A kategoria a synth-db SAJAT szava (Synth, Drum, Sampler, Misc), nem a mi
  taxonomiank. A hangszer-kategoriarendszer meg Kristof dontesere var (kanban
  f7f7f1c3), addig igy nyomon kovetheto, honnan jott, es negy ertek egy
  lepesben atmappelheto.
- Engine Type -> technology CSAK ott, ahol egyertelmu (Analog, Digital,
  Hybrid). A Controller, Sequencer, Modular, Vocoder, Filter NEM technologia,
  hanem eszkozfajta, azt itt nem hasznaljuk.
- Halott oldal ("No such synth :-("): SEMMIT nem ir bele, hanem a hangszert
  review_status='needs_review'-ra teszi az okkal egyutt. Nem torol.

Hasznalat:
    python3 db/read_synthdb_specs.py                 # szarazfutas
    python3 db/read_synthdb_specs.py --ingest        # ir is
    python3 db/read_synthdb_specs.py --db /masik.sqlite
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "synthdb"
DEAD_MARK = "No such synth"
TECH = {"analog": "analog", "digital": "digital", "hybrid": "hybrid"}
DEVICES = {"synth", "drum", "sampler", "misc"}


def field(lines, label):
    """A cimke-sor UTANI sor az ertek. Ures, ha a kovetkezo sor is cimke."""
    for i, line in enumerate(lines):
        if line.strip() == label and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def produced_year(lines):
    """A 'Produced:' sor evszama. A site 'YYYY - YYYY' alakot hasznal, a
    kezdo ev kell. Nehany oldalon a cimke es az ertek egy sorban all."""
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("Produced:"):
            continue
        rest = s[len("Produced:"):].strip()
        if not rest and i + 1 < len(lines):
            rest = lines[i + 1].strip()
        if rest.startswith("Legend"):
            return None
        m = re.search(r"\b(1[89]\d\d|20\d\d)\b", rest)
        if m:
            return int(m.group(1))
    return None


def read_cache(cache_dir=CACHE):
    """-> {url: {'dead':bool, 'year':int|None, 'device':str|None, 'tech':str|None}}"""
    out = {}
    for path in sorted(Path(cache_dir).glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        text = d.get("text", "")
        if DEAD_MARK in text:
            out[d["url"]] = {"dead": True, "year": None, "device": None, "tech": None}
            continue
        lines = text.split("\n")
        device = field(lines, "Device")
        engine = field(lines, "Engine Type").split(",")[0].strip().lower()
        out[d["url"]] = {
            "dead": False,
            "year": produced_year(lines),
            "device": device if device.lower() in DEVICES else None,
            "tech": TECH.get(engine),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--cache", default=str(CACHE),
                    help="a letoltott oldalak mappaja (alap: db/cache/synthdb)")
    args = ap.parse_args()

    cache_dir = Path(args.cache)
    if not cache_dir.is_dir():
        print(f"! nincs cache: {cache_dir}  (eloszor: python3 db/cache_synthdb_pages.py)")
        return 1
    pages = read_cache(cache_dir)
    print(f"{len(pages)} cache-elt oldal, ebbol halott: {sum(1 for p in pages.values() if p['dead'])}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT i.id, i.name, i.year, i.category, i.technology, i.source_url,
                  i.review_status, m.canonical_name AS mfr
           FROM instruments i JOIN manufacturers m ON m.id = i.manufacturer_id
           WHERE i.source_url LIKE '%synth-db.com%'"""
    ).fetchall()
    print(f"{len(rows)} hangszer hivatkozik synth-db forrasra")

    set_year, set_cat, set_tech, flag_dead = [], [], [], []
    missing, cats = 0, Counter()
    for r in rows:
        page = pages.get(r["source_url"])
        if page is None:
            missing += 1
            continue
        if page["dead"]:
            if r["review_status"] != "needs_review":
                flag_dead.append(r)
            continue
        if page["year"] and r["year"] is None:
            set_year.append((page["year"], r["id"]))
        if page["device"] and r["category"] is None:
            set_cat.append((page["device"], r["id"]))
            cats[page["device"]] += 1
        if page["tech"] and (r["technology"] in (None, "unknown")):
            set_tech.append((page["tech"], r["id"]))

    print(f"\nevszam kitoltheto:     {len(set_year)}")
    print(f"kategoria kitoltheto:  {len(set_cat)}   {dict(cats)}")
    print(f"technologia kitoltheto:{len(set_tech)}")
    print(f"halott forras, ellenorizendore megy: {len(flag_dead)}")
    if missing:
        print(f"({missing} hangszer forrasa nincs a cache-ben, kihagyva)")
    for r in flag_dead[:5]:
        print(f"    {r['mfr']} / {r['name']}")

    if not args.ingest:
        print("\n-- szarazfutas, semmi nem irodott. --ingest kell hozza --")
        return 0

    note = ("[synth-db kiolvasas 2026-09-02] A forras-oldal HALOTT: a synth-db "
            "sitemapja felsorolja, de az oldal maga azt valaszolja hogy nincs "
            "ilyen hangszer. A hangszer maga letezhet, de ez a forras nem "
            "igazol semmit. Emberi dontes: masik forras keresese, vagy torles, "
            "ha sitemap-szemet.")
    conn.executemany("UPDATE instruments SET year=? WHERE id=?", set_year)
    conn.executemany("UPDATE instruments SET category=? WHERE id=?", set_cat)
    conn.executemany("UPDATE instruments SET technology=? WHERE id=?", set_tech)
    conn.executemany(
        "UPDATE instruments SET review_status='needs_review', review_note=? WHERE id=?",
        [(note, r["id"]) for r in flag_dead])
    conn.commit()
    print(f"\nbeirva: {len(set_year)} evszam, {len(set_cat)} kategoria, "
          f"{len(set_tech)} technologia, {len(flag_dead)} ellenorizendo")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
