#!/usr/bin/env python3
"""Halott forras-hivatkozas levalasztasa a hangszerrol, a nyom megtartasaval.

Kristof jovahagyta 2026-09-03-an: "ne toroljunk semmit, mert a hangszerek
valodiak; a halott hivatkozas viszont kerüljon le roluk, mert nem igazol
semmit, es a jeloles maradjon, amig masik forras meg nem erositi oket."

MI A HELYZET
============
91 hangszernel a source_url egy synth-db oldalra mutat, amit a sitemap
felsorol, de a lap maga azt valaszolja, hogy nincs ilyen hangszer. A hangszer
maga nagy reszt valodi (Alesis QS6.1, Arturia MicroBrute SE), csak ez a forras
nem bizonyit rola semmit. Egy nem letezo lapra mutato source_url rosszabb a
semminel: ugy nez ki, mintha lenne forrasunk.

MERES 2026-09-03: a 91-bol 65 nevben VALTOZAT-JELOLES all -- zarojel, plusz,
vesszo vagy per (Quadrasynth (Plus), SD-1 (SD-1-32), EPS 16+ Rack). Ezeknel
maga a nev a magyarazat: a sitemap egy gyujto-cimet sorolt fel, aminek nincs
sajat lapja. A maradek 26 sima nevu, ott tenyleg masik forras kell.

MIT CSINAL
==========
- A source_url NULL lesz, de az URL BEKERUL a review_note szovegebe, tehat a
  nyom nem vesz el, csak nem allitja tobbe magarol, hogy bizonyitek.
- A review_status marad needs_review: a hangszer addig jelolt, amig masik
  forras meg nem erositi. Ezt Kristof az adminban egyesevel feloldhatja.
- A jegyzet megmondja, melyik esetrol van szo (valtozat-jeloles vagy sima nev),
  hogy a dontes ne igenyeljen ujabb nyomozast.
- Idempotens: egy mar levalasztott sort nem nyul meg ujra.

Hasznalat:
    python3 db/detach_dead_sources.py            # szarazfutas
    python3 db/detach_dead_sources.py --apply
"""
import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
VARIANT = re.compile(r"[()+/,]")
MARK = "[forras levalasztva"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, name, source_url, review_note FROM instruments
           WHERE review_status = 'needs_review'
             AND source_url IS NOT NULL
             AND review_note LIKE '%HALOTT%'"""
    ).fetchall()

    variant, plain = 0, 0
    for r in rows:
        if MARK in (r["review_note"] or ""):
            continue
        is_variant = bool(VARIANT.search(r["name"]))
        why = ("A nevben VALTOZAT-JELOLES all (zarojel, plusz, vesszo vagy per), "
               "tehat a sitemap egy gyujto-cimet sorolt fel, aminek nincs sajat lapja. "
               "A hangszer valoszinuleg valodi, a nev pontositasa vagy egy masik forras kell hozza."
               if is_variant else
               "Sima modellnev, tehat a hianyzo lapot nem a nevalak magyarazza. Masik forras kell hozza.")
        add = (f" {MARK} {day}] A halott forras-URL levaltva a mezorol, hogy ne latszodjon "
               f"bizonyiteknak, de a nyom megmarad: {r['source_url']} . {why}")
        if args.apply:
            conn.execute(
                "UPDATE instruments SET source_url = NULL, review_note = ? WHERE id = ?",
                ((r["review_note"] or "") + add, r["id"]))
        variant += is_variant
        plain += not is_variant

    if args.apply:
        conn.commit()
    print(f"halott forrasu, meg csatolt sor: {variant + plain}")
    print(f"  ebbol valtozat-jeloles a nevben: {variant}")
    print(f"  sima nev, masik forras kell:     {plain}")
    print("beirva." if args.apply else "-- szarazfutas, --apply kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
