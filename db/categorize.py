#!/usr/bin/env python3
"""Kategóriák kezelése -- a hangszer több kategóriába is tartozhat.

Kristóf szabálya (2026-09-01), ami nélkül ez a mező pont annyit ér, mint a
szabad szöveg amit lecserél:

    Egy kategória akkor kerül a hangszerre, ha MEGHATÁROZÓ rá nézve, nem akkor,
    ha a funkció pusztán jelen van.

Az ő példája: a Korg Trinity workstation. Van benne szekvenszer, némelyikben
sampler is, de egyik sem meghatározó, tehát azokat NEM kapja meg. A háromsoros
orgona viszont orgona is és szintetizátor is, mert az egyik manuál valóban
analóg szintetizátor.

Az `instruments.category` oszlop az ELSŐDLEGES kategória tükre, mert az admin és
a statikus oldal generátora ma abból olvas. Minden írás után frissül magától.

Használat:
  python3 db/categorize.py --list                       # kategóriák darabszámmal
  python3 db/categorize.py --show 1449                  # egy hangszer kategóriái
  python3 db/categorize.py --add 1449 "drum machine" --primary
  python3 db/categorize.py --remove 1449 "drum machine"
  python3 db/categorize.py --rename "Digital Grand" "digital piano"
  python3 db/categorize.py --merge "V-Drums" "elektronikus dobkeszlet"
  python3 db/categorize.py --sync-mirror                # tükör újraépítése
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"


def connect():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def cat_id(con, name, create=False):
    row = con.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    if not create:
        sys.exit(f"nincs ilyen kategória: {name!r} (--list mutatja a meglévőket)")
    con.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def sync_mirror(con):
    """instruments.category = az elsődleges kategória, vagy NULL ha nincs."""
    con.execute("""
        UPDATE instruments SET category = (
            SELECT c.name FROM instrument_categories ic
            JOIN categories c ON c.id = ic.category_id
            WHERE ic.instrument_id = instruments.id AND ic.is_primary = 1
            LIMIT 1)""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", type=int, metavar="INSTRUMENT_ID")
    ap.add_argument("--add", nargs=2, metavar=("INSTRUMENT_ID", "CATEGORY"))
    ap.add_argument("--remove", nargs=2, metavar=("INSTRUMENT_ID", "CATEGORY"))
    ap.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"))
    ap.add_argument("--merge", nargs=2, metavar=("FROM", "INTO"))
    ap.add_argument("--sync-mirror", action="store_true")
    ap.add_argument("--primary", action="store_true",
                    help="--add mellett: ez legyen az elsődleges kategória")
    args = ap.parse_args()
    con = connect()

    if args.list:
        rows = con.execute("""
            SELECT c.name, COUNT(ic.instrument_id)
            FROM categories c LEFT JOIN instrument_categories ic ON ic.category_id = c.id
            GROUP BY c.id ORDER BY 2 DESC, 1""").fetchall()
        unc = con.execute("""SELECT COUNT(*) FROM instruments
            WHERE id NOT IN (SELECT instrument_id FROM instrument_categories)""").fetchone()[0]
        for name, n in rows:
            print(f"{n:6d}  {name}")
        print(f"\n{len(rows)} kategória, {unc} hangszer kategória nélkül")
        return

    if args.show is not None:
        name = con.execute("SELECT name FROM instruments WHERE id=?", (args.show,)).fetchone()
        if not name:
            sys.exit(f"nincs ilyen hangszer: {args.show}")
        print(name[0])
        for cname, prim in con.execute("""
                SELECT c.name, ic.is_primary FROM instrument_categories ic
                JOIN categories c ON c.id = ic.category_id
                WHERE ic.instrument_id = ? ORDER BY ic.is_primary DESC, c.name""",
                (args.show,)):
            print(f"  {'*' if prim else ' '} {cname}")
        return

    if args.add:
        iid, cname = int(args.add[0]), args.add[1]
        if not con.execute("SELECT 1 FROM instruments WHERE id=?", (iid,)).fetchone():
            sys.exit(f"nincs ilyen hangszer: {iid}")
        cid = cat_id(con, cname, create=True)
        if args.primary:
            con.execute("UPDATE instrument_categories SET is_primary=0 WHERE instrument_id=?", (iid,))
        con.execute("""INSERT INTO instrument_categories (instrument_id, category_id, is_primary)
                       VALUES (?,?,?)
                       ON CONFLICT(instrument_id, category_id)
                       DO UPDATE SET is_primary=excluded.is_primary""",
                    (iid, cid, 1 if args.primary else 0))
        sync_mirror(con); con.commit()
        print(f"{cname} -> hangszer {iid}" + (" (elsődleges)" if args.primary else ""))
        return

    if args.remove:
        iid, cname = int(args.remove[0]), args.remove[1]
        cid = cat_id(con, cname)
        con.execute("DELETE FROM instrument_categories WHERE instrument_id=? AND category_id=?",
                    (iid, cid))
        sync_mirror(con); con.commit()
        print(f"{cname} levéve a {iid} hangszerről")
        return

    if args.rename:
        old, new = args.rename
        cid = cat_id(con, old)
        if con.execute("SELECT 1 FROM categories WHERE name=?", (new,)).fetchone():
            sys.exit(f"{new!r} már létezik -- használd a --merge kapcsolót")
        con.execute("UPDATE categories SET name=? WHERE id=?", (new, cid))
        sync_mirror(con); con.commit()
        n = con.execute("SELECT COUNT(*) FROM instrument_categories WHERE category_id=?",
                        (cid,)).fetchone()[0]
        print(f"{old} -> {new}   ({n} hangszert érint, egyetlen sor módosult)")
        return

    if args.merge:
        src, dst = args.merge
        sid, did = cat_id(con, src), cat_id(con, dst, create=True)
        if sid == did:
            sys.exit("ugyanaz a kategória")
        moved = con.execute("SELECT COUNT(*) FROM instrument_categories WHERE category_id=?",
                            (sid,)).fetchone()[0]
        # a hangszer már lehet a célkategóriában is: ilyenkor csak eldobjuk a régit
        con.execute("""INSERT OR IGNORE INTO instrument_categories
                       (instrument_id, category_id, is_primary)
                       SELECT instrument_id, ?, is_primary FROM instrument_categories
                       WHERE category_id=?""", (did, sid))
        con.execute("DELETE FROM instrument_categories WHERE category_id=?", (sid,))
        con.execute("DELETE FROM categories WHERE id=?", (sid,))
        sync_mirror(con); con.commit()
        print(f"{src} beolvasztva ide: {dst}   ({moved} hangszer)")
        return

    if args.sync_mirror:
        sync_mirror(con); con.commit()
        print("tükör frissítve")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
