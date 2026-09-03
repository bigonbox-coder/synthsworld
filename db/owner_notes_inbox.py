#!/usr/bin/env python3
"""Kristof megjegyzesei a hangszer-jelolesekre: a bejovo lista es a lezarasa.

Kristof, 2026-09-03 (hanguzenet): "a megjegyzeseimet azokat nezd meg es az
alapjan vagy tegyel javaslatot vagy epitsd bele a kutatasba."

A 0031 migracio ota harom valasz van egy jelolesre: Marad, Torles, es a
Megjegyzes. Az elso ketto lezarja a sort magatol, a harmadik NEM: az egy
allitas, amivel dolgozni kell. Ez a script az a hely, ahol ezek osszegyulnek,
kulonben csak akkor latnam oket, ha Kristof szol -- pont az ellenkezoje annak,
amit kert.

  --list      (alap) mind, amire valaszolt es meg nem dolgoztam fel
  --resolve   ha kesz: a jeloles lekerul, es a review_note-ba bekerul, MIT
              tettem az alapjan. Kristof szovege NEM tunik el, marad az
              owner_note-ban, mert az a bizonyitek arra, honnan tudjuk.

Hasznalat:
  python3 db/owner_notes_inbox.py
  python3 db/owner_notes_inbox.py --resolve 1448 --did "Szetszedve ket sorra: ..."
"""
import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", type=int, metavar="ID")
    ap.add_argument("--did", help="--resolve melle: mit tettem a megjegyzes alapjan")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    if args.resolve:
        if not args.did:
            ap.error("a --resolve melle kell a --did: mit tettel az alapjan")
        row = con.execute(
            "SELECT id, manufacturer_id, name, year, review_note, owner_note "
            "FROM instruments WHERE id=?", (args.resolve,)).fetchone()
        if not row:
            raise SystemExit(f"nincs ilyen hangszer: {args.resolve}")
        note = ((row["review_note"] or "") +
                f' [megjegyzes feldolgozva] Kristof: "{row["owner_note"]}" -- {args.did}')
        con.execute(
            "UPDATE instruments SET review_status=NULL, review_note=? WHERE id=?",
            (note, args.resolve))
        con.execute(
            "INSERT INTO manufacturer_review_log (manufacturer_id, action, note) "
            "VALUES (?, 'note_added', ?)",
            (row["manufacturer_id"],
             f'Kristof megjegyzese feldolgozva: {row["name"]} -- {args.did}'))
        con.commit()
        print(f'kesz: {row["name"]} (#{row["id"]})')
        return

    rows = con.execute(
        """SELECT i.id, i.name, i.year, i.owner_note, i.owner_note_at,
                  i.review_note, m.canonical_name AS maker, m.id AS mid
           FROM instruments i JOIN manufacturers m ON m.id = i.manufacturer_id
           WHERE i.review_status = 'owner_answered'
           ORDER BY i.owner_note_at"""
    ).fetchall()
    if not rows:
        print("Nincs feldolgozatlan megjegyzes.")
        return
    print(f"{len(rows)} megjegyzes var feldolgozasra:\n")
    for r in rows:
        year = f' ({r["year"]})' if r["year"] else ""
        print(f'#{r["id"]}  {r["maker"]} {r["name"]}{year}   [{r["owner_note_at"][:16]}]')
        print(f'  KRISTOF: {r["owner_note"]}')
        print(f'  a jeloles oka: {(r["review_note"] or "")[:160]}')
        print(f'  lezaras: python3 db/owner_notes_inbox.py --resolve {r["id"]} --did "..."\n')


if __name__ == "__main__":
    main()
