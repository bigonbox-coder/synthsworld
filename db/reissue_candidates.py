#!/usr/bin/env python3
"""Ujrakiadas-gyanus sorok keresese (0030 utan).

Kristof, 2026-09-03: "a retro divat miatt sok hangszert kiadtak ujra vagy
ugyanazon a neven maskent (...) ezek kulon termekek tehat kulon is kezeljuk."

Ez a script NEM ir, csak jelolteket sorol. A dontes emberi, mert mind a harom
jel gyenge onmagaban -- viszont egyutt nagyon jol szur.

Harom jel:

  1. evszam-ellentmondas
     A rogzitett ev UJABB, mint a korabeli hirdetes eve. Ha a kulonbseg legalabb
     ket ev, akkor a rogzitett evszam nagy esellyel az UJRAKIADASE, es a sor ket
     terméket mos ossze. Igy talaltuk meg a Moog System 35-ot (nalunk 2015,
     kozben 1974-es brosura) es az 55-ot (nalunk 2016, 1980-as arlista).
     A hirdetes evet a link CIMKEJEBOL olvassuk, nem a poszt datumabol: a
     blogspot-URL 2017-et mond egy 1980-as arlistara.

  2. modern evszam, regi forras
     year >= 2000, de van 1995 elotti hirdetese vagy dokumentuma. Ugyanaz a
     gyanu, csak nem szamszeru ellentmondasbol, hanem a forras korabol.

  3. azonos nev, mas gyarto
     Ket sor ugyanazzal a normalizalt nevvel, kulonbozo gyartonal. Harom eset
     rejtozik itt, es a script nem donti el, melyik:
       - duplikalt GYARTO-rekord (PAiA kontra Paia Corporation) -> gyarto-osszevonas
       - markavandorlas (ARP Chroma -> Rhodes Chroma) -> egy termek, ket sor
       - valodi kulon termek (Casio VL-1 kontra Yamaha VL1) -> maradjon ket sor
     Ha ujrakiadasrol van szo, akkor a kesobbi sor kap edition='reissue' vagy
     'clone' erteket es reissue_of_id-t az eredetire.

Hasznalat:
  python3 db/reissue_candidates.py            # osszefoglalo a kepernyore
  python3 db/reissue_candidates.py --report   # + markdown a db/leads/ ala
"""
import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
LEADS = Path(__file__).resolve().parent / "leads"

YEAR_RE = re.compile(r"\b(19[4-9]\d|20[0-2]\d)\b")
# Kulonbseg, ami alatt nem szolunk. Egy ev elteres a hirdetes es a megjelenes
# kozott normalis (a hirdetes lehet a kovetkezo evi szamban), ket ev mar nem az.
MIN_GAP = 2
MODERN = 2000
OLD_SOURCE = 1995


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def earliest_source_year(con):
    """Instrument id -> (legkorabbi forras-ev, cimke, url).

    A cimkebol olvasunk evszamot ("... brochure, 1974"), mert a link datuma a
    POSZT datuma. Az 1940 elotti es a mai evnel kesobbi talalatot eldobjuk.
    """
    out = {}
    this_year = date.today().year
    rows = con.execute(
        "SELECT instrument_id, label, url FROM external_links "
        "WHERE instrument_id IS NOT NULL AND label IS NOT NULL"
    ).fetchall()
    for r in rows:
        years = [int(y) for y in YEAR_RE.findall(r["label"])]
        years = [y for y in years if 1940 <= y <= this_year]
        if not years:
            continue
        y = min(years)
        cur = out.get(r["instrument_id"])
        if cur is None or y < cur[0]:
            out[r["instrument_id"]] = (y, r["label"], r["url"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="markdown a db/leads/ ala")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    insts = con.execute(
        """SELECT i.id, i.name, i.year, i.edition, i.reissue_of_id,
                  m.id AS mid, m.canonical_name AS maker
           FROM instruments i JOIN manufacturers m ON m.id = i.manufacturer_id"""
    ).fetchall()
    src = earliest_source_year(con)

    conflicts, modern_old, decided = [], [], 0
    for it in insts:
        if it["edition"] != "original" or it["reissue_of_id"]:
            decided += 1
            continue
        s = src.get(it["id"])
        if not s:
            continue
        if it["year"] and it["year"] - s[0] >= MIN_GAP:
            conflicts.append((it, s, it["year"] - s[0]))
        elif it["year"] and it["year"] >= MODERN and s[0] < OLD_SOURCE:
            modern_old.append((it, s))

    groups = defaultdict(list)
    for it in insts:
        k = norm(it["name"])
        if len(k) >= 3:
            groups[k].append(it)
    cross = [v for v in groups.values() if len({x["mid"] for x in v}) > 1]
    cross.sort(key=lambda v: v[0]["name"].lower())

    conflicts.sort(key=lambda t: -t[2])
    print(f"evszam-ellentmondas (>= {MIN_GAP} ev): {len(conflicts)}")
    for it, s, gap in conflicts[:15]:
        print(f"  {it['maker']} {it['name']}: nalunk {it['year']}, forras {s[0]} "
              f"({gap} ev) -- {s[1][:70]}")
    print(f"\nmodern evszam ({MODERN}+) regi ({OLD_SOURCE} elotti) forrassal: {len(modern_old)}")
    for it, s in modern_old[:10]:
        print(f"  {it['maker']} {it['name']}: {it['year']} vs {s[0]}")
    print(f"\nazonos nev mas gyartonal: {len(cross)} csoport")
    print(f"mar eldontott (edition vagy reissue_of_id all): {decided}")

    if args.report:
        LEADS.mkdir(exist_ok=True)
        out = LEADS / f"{date.today():%Y%m%d}-ujrakiadas-jeloltek.md"
        L = ["# Ujrakiadas-jeloltek", "",
             f"Generalva: {date.today()}. Forras: db/reissue_candidates.py.",
             "A dontes emberi. Amelyik sor tenyleg ket termeket mos ossze, ott a",
             "meglevo sor kap `edition='reissue'`-t, es melle kerul az eredeti.",
             "", f"## 1. Evszam-ellentmondas ({len(conflicts)})", "",
             "A rogzitett ev ujabb, mint a hirdetes eve.", "",
             "| gyarto | hangszer | nalunk | forras eve | elteres | a forras |",
             "|---|---|---|---|---|---|"]
        for it, s, gap in conflicts:
            L.append(f"| {it['maker']} | {it['name']} | {it['year']} | {s[0]} | "
                     f"{gap} | [{s[1][:60]}]({s[2]}) |")
        L += ["", f"## 2. Modern evszam, regi forras ({len(modern_old)})", "",
              "| gyarto | hangszer | nalunk | forras eve | a forras |", "|---|---|---|---|---|"]
        for it, s in modern_old:
            L.append(f"| {it['maker']} | {it['name']} | {it['year']} | {s[0]} | "
                     f"[{s[1][:60]}]({s[2]}) |")
        L += ["", f"## 3. Azonos nev, mas gyarto ({len(cross)} csoport)", "",
              "Harom eset keveredik: duplikalt gyarto-rekord, markavandorlas,",
              "valodi nevegybeeses. Csak az elso ketto igenyel lepest.", ""]
        for v in cross:
            L.append("- " + " | ".join(
                f"**{x['maker']}** {x['name']} ({x['year'] or '?'}) #{x['id']}" for x in v))
        out.write_text("\n".join(L) + "\n")
        print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
