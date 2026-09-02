#!/usr/bin/env python3
"""synth-db.com: gyarto- es hangszernevek a sitemapbol, oldalletoltes nelkul.

Kristof adta a forrast 2026-09-02, es engedelyezte a beemelest: "A szintiket,
gyartokat beemelheted."

MIERT INGYENES EZ
=================
A sitemap cimei maguk hordozzak az adatot:
    http://www.synth-db.com/synths/<Gyarto>/<Modell>/<Modell>.php
Tehat a gyarto- es modellnevekhez EGYETLEN oldalt sem kell letolteni, es egy
modellt sem kell modellel kiolvastatni. Egy darab sitemap-lekeres az egesz.

Evszam es kategoria NINCS a cimben, azok az oldalak szoveges leirasaban
ulnek. Az mar feldolgozas, tehat kulon kerdes: a processing_backlog tablaban
all felirva, megmerve (lasd a 0025-os migraciot).

KET DOLGOT CSINAL
=================
1. A MAR ISMERT gyartoinkhoz felveszi a hianyzo hangszereket (nev +
   forras-URL, evszam es kategoria nelkul, mert azt a cim nem mondja meg).
2. Az ISMERETLEN gyartoneveket a varolistara teszi.

A NEVVALTOZAT-CSAPDA
====================
A varolistara iras nem naiv nevegyezes-vizsgalat. A synth-db rovid alakokat
hasznal ("ARP", "E-mu", "Buchla"), nalunk viszont a teljes cegnev all
("ARP Instruments", "E-mu Systems", "Buchla Electronic Musical Instruments").
A queue_dupe_check.py a FORDITOTT iranyt fogja meg (a varolistas nev tartalmaz
egy meglevo gyartonevet), ezt az iranyt nem. Ezert az itt felvett nevet
needs_review-ra tesszuk, ha egy meglevo gyartonev SZOHATARON KEZDODIK vele --
igy nem keletkezik csendben egy masodik ARP.

Hasznalat:
    python3 db/harvest_synthdb.py --dry-run
    python3 db/harvest_synthdb.py --ingest
"""

import argparse
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
SITEMAP = "http://www.synth-db.com/sitemap.xml"   # HTTPS NINCS, ne eroltesd
UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")
SOURCE = "synth-db.com"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def key(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def fetch_sitemap():
    r = subprocess.run(["curl", "-sSL", "--max-time", "60", "-A", UA, SITEMAP],
                       capture_output=True, text=True)
    if r.returncode != 0 or "<loc>" not in r.stdout:
        print("! a sitemap nem jott le")
        return []
    return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.stdout)


def parse(urls):
    """-> {(gyarto, modell): url}. A cim ket elso szegmense a ket nev."""
    out = {}
    for u in urls:
        if "/synths/" not in u:
            continue
        parts = urllib.parse.unquote(u.split("/synths/", 1)[1]).split("/")
        if len(parts) < 2:
            continue
        mfr, model = parts[0].strip(), parts[1].strip()
        if mfr and model:
            out[(mfr, model)] = u
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="irjon is, ne csak mutasson")
    args = ap.parse_args()

    pairs = parse(fetch_sitemap())
    if not pairs:
        return 1
    print(f"a sitemap {len(pairs)} hangszer-oldalt sorol, "
          f"{len({m for m, _ in pairs})} gyartotol")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    known = {}
    for r in conn.execute("SELECT id, canonical_name FROM manufacturers"):
        known[key(r["canonical_name"])] = (r["id"], r["canonical_name"])
    for r in conn.execute("SELECT h.name, m.id, m.canonical_name FROM manufacturer_name_history h "
                          "JOIN manufacturers m ON m.id = h.manufacturer_id"):
        known.setdefault(key(r["name"]), (r["id"], r["canonical_name"]))
    have_inst = {(r["mid"], key(r["name"])) for r in conn.execute(
        "SELECT manufacturer_id AS mid, name FROM instruments")}
    in_queue = {key(r["manufacturer_name"]) for r in conn.execute(
        "SELECT manufacturer_name FROM discovery_queue")}

    new_inst, new_names, variants = [], [], []
    for (mfr, model), url in sorted(pairs.items()):
        hit = known.get(key(mfr))
        if hit:
            if (hit[0], key(model)) not in have_inst:
                new_inst.append((hit[0], hit[1], model, url))
            continue
        if key(mfr) in in_queue:
            continue
        # nevvaltozat-e: egy meglevo gyartonev SZOHATARON ezzel kezdodik?
        longer = [v[1] for k, v in known.items()
                  if k.startswith(key(mfr) + " ")]
        (variants if longer else new_names).append((mfr, longer))
        in_queue.add(key(mfr))

    print(f"\nuj hangszer ismert gyartohoz: {len(new_inst)}")
    from collections import Counter
    for m, n in Counter(x[1] for x in new_inst).most_common(8):
        print(f"    {m:28s} {n}")
    print(f"\nuj gyartonev a varolistara: {len(new_names)}")
    print("    " + ", ".join(n for n, _ in new_names[:25]))
    print(f"\nNEVVALTOZAT-GYANUS, needs_review-ra megy: {len(variants)}")
    for n, longer in variants:
        print(f"    {n:24s} ~ {', '.join(longer)}")

    if not args.ingest:
        print("\n-- szarazfutas, semmi nem irodott. --ingest kell hozza --")
        return 0

    for mid, _, model, url in new_inst:
        conn.execute("INSERT INTO instruments (manufacturer_id, name, year, category, source_url) "
                     "VALUES (?, ?, NULL, NULL, ?)", (mid, model, url))
    for name, longer in new_names + variants:
        note = f"synth-db.com sitemap, {now_iso()[:10]}"
        status = "found"
        if longer:
            status = "needs_review"
            note += (f" | NEVVALTOZAT-GYANU: a tablaban mar all "
                     f"{', '.join(longer)}. Ha ugyanaz a ceg, ez a sor lezarhato "
                     f"es a rovid alak a nev-tortenetbe valo.")
        conn.execute("INSERT INTO discovery_queue (manufacturer_name, status, notes) "
                     "VALUES (?, ?, ?)", (name, status, note))
    conn.commit()
    print(f"\nbeirva: {len(new_inst)} hangszer, "
          f"{len(new_names)} uj varolistas nev, {len(variants)} nevvaltozat-gyanus sor")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
