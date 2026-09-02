#!/usr/bin/env python3
"""Varolistas duplikatumok kiszurese, mielott egy napi kutatasi kort elvinnenek.

MIERT
=====
A napi kutatas EGY gyartot dolgoz fel. Ha az a nev olyat takar, ami mar bent
van a tablaban, az a kor karba veszett. 2026-09-02-en kezzel futottam bele:
a varolistan ott allt a "Novation Digital Music Systems", miközben a "Novation"
mar reg bent volt.

Kristof jovahagyta a jelolest (2026-09-02), azzal a kikotessel, hogy ez CSAK
jelolje meg oket, ne vonjon ossze semmit magatol. Az osszevonas emberi dontes.

HAROM ESET, ES A KULONBSEG KOZTUK A LENYEG
==========================================
A meres (2026-09-02) mutatta meg, hogy a naiv "pontos nevegyezes = felesleges
sor" szabaly HIBAS lett volna. A 28 pontos egyezesbol csak 7 felesleges:

1. PONTOS nevegyezes, es a gyarto MAR KI VAN KUTATVA (confirmed/needs_review)
   -> a sor tenyleg elavult, jelolheto. 7 ilyen van.
2. PONTOS nevegyezes, de a gyarto csak egy UNRESEARCHED csonk (rokoncegkent
   jott letre, nincs mogotte kutatas) -> a sor NEM felesleges, sot, eppen az
   inditana el a kutatast. Ezeket bantani sulyos hiba lenne. 21 ilyen van.
3. TARTALMAZAS: a varolistas nev magaban foglal egy meglevo gyartonevet
   (Yamaha Drums, Oberheim Electronics) -> ez lehet ugyanaz a ceg mas neven,
   de lehet onallo felvetel is. Ember donti el, a script csak jelol. 5 ilyen.

Hasznalat:
    python3 db/queue_dupe_check.py            # csak mutatja
    python3 db/queue_dupe_check.py --apply    # jeloli is (needs_review)
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
RESEARCHED = ("confirmed", "needs_review")

# Melyik kapcsolat-tipus arul el sajat gyartast, es melyik csak tulajdonlast.
# Lasd a 0024-es migracio indoklasat: a csonkok kozott ez a valaszvonal.
MAKER_RELATIONS = {"collaboration", "successor", "supplier", "merged_with"}
OWNER_RELATIONS = {"acquired_by", "acquired", "part_of", "subsidiary_of",
                   "owner_of", "sold_brand_to"}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def key(s):
    """Nevkulcs: kisbetu, irasjelek nelkul, egy szokozzel. Az "Octave Plateau"
    es az "Octave-Plateau" ugyanaz, a "Yamaha" es a "Yamaha Drums" nem."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def build_index(conn):
    """Nevkulcs -> (gyarto id, kanonikus nev, kikutatottsag). A nev-tortenet is
    beleszamit, mert egy regi cegnev ugyanugy duplikatum."""
    idx = {}
    for r in conn.execute("SELECT id, canonical_name, confidence_level FROM manufacturers"):
        idx[key(r["canonical_name"])] = (r["id"], r["canonical_name"], r["confidence_level"])
    for r in conn.execute(
            "SELECT h.name, m.id, m.canonical_name, m.confidence_level "
            "FROM manufacturer_name_history h JOIN manufacturers m ON m.id = h.manufacturer_id"):
        idx.setdefault(key(r["name"]), (r["id"], r["canonical_name"], r["confidence_level"]))
    return idx


def classify(conn):
    idx = build_index(conn)
    # a tartalmazas-kereseshez a hosszabb nevek elol, hogy a legpontosabb nyerjen
    by_len = sorted(idx.items(), key=lambda kv: -len(kv[0]))
    stale, stubs, contained = [], [], []

    for r in conn.execute(
            "SELECT id, manufacturer_name, notes FROM discovery_queue "
            "WHERE status = 'found' ORDER BY id"):
        qk = key(r["manufacturer_name"])
        hit = idx.get(qk)
        if hit:
            (stale if hit[2] in RESEARCHED else stubs).append((r, hit))
            continue
        for mk, hit in by_len:
            if mk and mk != qk and re.search(r"(^|\s)" + re.escape(mk) + r"(\s|$)", qk):
                contained.append((r, hit))
                break
    return stale, stubs, contained


def stub_is_maker(conn, mid):
    """Egy csonkrol a KAPCSOLAT TIPUSA mondja meg, hogy maga is gyarto-e, vagy
    csak tulajdonos, akit kontextuskent vettunk fel. None = nem tudjuk."""
    kinds = {r["relation_type"] for r in conn.execute(
        "SELECT relation_type FROM manufacturer_relations "
        "WHERE manufacturer_id = ? OR related_manufacturer_id = ?", (mid, mid))}
    if kinds & MAKER_RELATIONS:
        return True
    if kinds & OWNER_RELATIONS:
        return False
    return None


def mark(conn, row, hit, why):
    note = (row["notes"] or "").strip()
    add = (f"[dupe-check {now_iso()[:10]}] {why} Meglevo rekord: "
           f"{hit[1]} (id {hit[0]}, {hit[2]}). Osszevonas EMBERI dontes, a script nem vont ossze.")
    conn.execute(
        "UPDATE discovery_queue SET status = 'needs_review', notes = ?, updated_at = ? WHERE id = ?",
        ((note + " | " + add) if note else add, now_iso(), row["id"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="jelolje is meg, ne csak mutassa")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    stale, stubs, contained = classify(conn)

    print(f"1. PONTOS egyezes, a gyarto mar ki van kutatva -> elavult sor: {len(stale)}")
    for r, h in stale:
        print(f"   queue#{r['id']:4d} {r['manufacturer_name']:38s} == {h[1]} (id {h[0]})")

    print(f"\n2. PONTOS egyezes, de a gyarto csak UNRESEARCHED csonk -> BEKEN HAGYVA: {len(stubs)}")
    print("   (ezek nem felesleges sorok: eppen ezek inditanak kutatast a csonkokra)")
    makers = []
    for r, h in stubs:
        kind = stub_is_maker(conn, h[0])
        tag = {True: "GYARTO  -> elore", False: "tulajdonos", None: "nem tudni"}[kind]
        if kind:
            makers.append((r, h))
        print(f"   queue#{r['id']:4d} {r['manufacturer_name']:38s} {tag}")
    print(f"   ebbol sajat jogan gyarto, tehat elore sorolando: {len(makers)}")

    print(f"\n3. TARTALMAZAS, ember donti el: {len(contained)}")
    for r, h in contained:
        print(f"   queue#{r['id']:4d} {r['manufacturer_name']:38s} ~~ {h[1]} (id {h[0]})")

    if args.apply:
        for r, h in stale:
            mark(conn, r, h, "A nev PONTOSAN egyezik egy mar kikutatott gyartoeval.")
        for r, h in contained:
            mark(conn, r, h, "A nev TARTALMAZ egy meglevo gyartonevet.")
        for r, h in makers:
            conn.execute("UPDATE discovery_queue SET priority = 1, updated_at = ? WHERE id = ?",
                         (now_iso(), r["id"]))
        conn.commit()
        print(f"\n{len(stale) + len(contained)} sor needs_review lett. "
              f"A {len(stubs)} csonk-sor statusza erintetlen, ebbol {len(makers)} kapott elsobbseget.")
    else:
        print(f"\n{len(stale) + len(contained)} sor kapna jelolest. -- szarazfutas, --apply kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
