#!/usr/bin/env python3
"""A kozismert nevet teszi fonevve, a teljes cegnevet ala.

Kristof, 2026-09-02: a fonev a kozismert alak, alatta kicsiben a hosszu.
Eddig forditva volt: a canonical_name-ben a jogi nev allt, a rovid alak sehol.

A PAROK NEM TALALGATASBOL JONNEK. Mindegyik ugy kerult ide, hogy a rovid alak
MAR SZEREPELT az adatbazisban: vagy a manufacturer_name_history-ban, vagy a
discovery_queue-n (oda kulso forras hozta be). Ket minta:
  * elotag:  a hosszu nev a rovidnek a folytatasa  (Korg Inc. <- Korg)
  * betuszo: a rovid a hosszu kezdobetui           (EML <- Electronic Music Laboratories)

AMIT SZANDEKOSAN KIHAGYTAM, es miert -- ezek a talalati listan ott voltak, de
gepiesen atvenni oket hiba lett volna:
  * Akai Professional <- Akai:  az Akai Professional NEM az Akai rovidebb neve,
    hanem egy kulon marka. Osszevonni ket ceget jelentene.
  * Octave-Plateau <- Octave:   itt a HOSSZABB alak a kozismert, nem a rovid.
  * New England Digital <- NED: ugyanez, a teljes nev a bevett.
  * E-mu Systems <- EMS:        HAMIS talalat. Az EMS onallo ceg (id 26,
    Electronic Music Studios), csak a kezdobetuk esnek egybe.

Hasznalat:
    python3 db/split_long_names.py           # megmutatja
    python3 db/split_long_names.py --apply   # ir is
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"

# (gyarto id, kozismert nev, teljes ceg-alak)
PAIRS = [
    (1,  "Moog",          "Moog Music"),
    (4,  "Roland",        "Roland Corporation"),
    (5,  "Korg",          "Korg Inc."),
    (14, "ARP",           "ARP Instruments"),
    (21, "Buchla",        "Buchla Electronic Musical Instruments"),
    (22, "E-mu",          "E-mu Systems"),
    (24, "Kurzweil",      "Kurzweil Music Systems"),
    (28, "Waldorf",       "Waldorf Music"),
    (30, "EDP",           "Electronic Dream Plant"),
    (33, "Kawai",         "Kawai Musical Instruments"),
    (35, "Hammond",       "Hammond Organ Company"),
    (36, "Serge Modular", "Serge Modular Music Systems"),
    (42, "Formanta",      "Formanta Radio Factory"),
    (61, "Baldwin",       "Baldwin Piano Company"),
    (62, "Gibson",        "Gibson Guitar Corporation"),
    (68, "EML",           "Electronic Music Laboratories"),
    (70, "PAiA",          "PAiA Electronics, Inc."),
    (80, "Clavia",        "Clavia DMI AB"),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    changed = skipped = 0

    for mid, short, long in PAIRS:
        row = conn.execute("SELECT canonical_name, long_name FROM manufacturers WHERE id = ?",
                           (mid,)).fetchone()
        if not row:
            print(f"  ! nincs ilyen id: {mid}")
            continue
        if row["canonical_name"] == short and row["long_name"] == long:
            skipped += 1
            continue
        if row["canonical_name"] != long:
            print(f"  ! id{mid}: a tablaban '{row['canonical_name']}' all, nem '{long}'. Kihagyva.")
            skipped += 1
            continue
        print(f"  id{mid:3d}  '{long}'  ->  fonev '{short}', alatta '{long}'")
        changed += 1
        if args.apply:
            conn.execute("UPDATE manufacturers SET canonical_name = ?, long_name = ?, updated_at = ? "
                         "WHERE id = ?", (short, long, now_iso(), mid))
            # a teljes alak nev-tortenetkent is maradjon meg, evszam nelkul,
            # hogy a kulso forrasok hosszu neve tovabbra is talaljon
            if not conn.execute("SELECT 1 FROM manufacturer_name_history "
                                "WHERE manufacturer_id = ? AND lower(name) = lower(?)",
                                (mid, long)).fetchone():
                conn.execute("INSERT INTO manufacturer_name_history "
                             "(manufacturer_id, name, start_year, end_year) VALUES (?, ?, NULL, NULL)",
                             (mid, long))
    if args.apply:
        conn.commit()
    print(f"\n{changed} valtozott, {skipped} maradt")
    if not args.apply:
        print("-- szarazfutas, --apply kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
