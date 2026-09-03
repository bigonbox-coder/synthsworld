#!/usr/bin/env python3
"""synth-db markanev -> a mi gyartonk, kezzel ellenorzott nevparok alapjan.

MIERT KELL
==========
A synth-db oldal-cache (db/cache/synthdb, 1903 oldal) markanevet is tartalmaz.
A read_synthdb_specs.py csak azokat a hangszereket eri el, amik MAR bent vannak
nalunk es synth-db forras-URL-lel. 2026-09-03-i meres: a cache 208 markajabol
155 nem talalt gyarto-rekordot, DE ebbol 13 csak NEVALAKBAN tert el attol,
ahogy mi hivjuk ugyanazt a ceget. Peldaul a cache "Akai" nevet ir, nalunk a
rekord "Akai Professional"; a cache "Sequential Circuits", nalunk "Sequential".

Ezeket a parokat NEM a script talalja ki: emberi ellenorzes utan allnak itt,
modellistaval egyutt igazolva. A hamis talalatok (Elektronika != Elektron,
KOMA Elektronik != Elektron, EMI != Eminent, RMI != RMIF) SZANDEKOSAN nincsenek
benne, es a REJECTED szotarban all, hogy miert, nehogy valaki fel ev mulva
ujra felvesse.

MIERT NEM A name_history-BA MEGY
================================
Mert az egy allitas a cegrol ("igy hivtak korabban"), es a 9 parbol csak
nehanyra igaz. A "Fairlight CMI" nem cegnev, hanem a hangszer neve; az "Akai"
nem a mi rekordunk regi neve, hanem az anyamarka. A nevpar ITT all, egy
verziokezelt fajlban, ahol lathato es visszavonhato.

MIT CSINAL
==========
Csak modellnevet es forras-URL-t ir be, semmi mast. Az evszamot, a kategoriat
es a technologiat utana a read_synthdb_specs.py tolti ki UGYANABBOL a cache-bol,
es az CSAK ures mezot tolt, tehat meglevo adatot nem ir felul. Meglevo
hangszernevet (kis- es nagybetutol fuggetlenul) atlep.

Hasznalat:
    python3 db/import_synthdb_brands.py            # szarazfutas
    python3 db/import_synthdb_brands.py --apply
    python3 db/read_synthdb_specs.py --ingest      # utana, a mezokert
"""
import argparse
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "synthdb"
DEAD_MARK = "No such synth"

# synth-db markanev -> a mi canonical_name-unk. Mindegyik par mellett az all,
# MI IGAZOLJA: a cache modellistaja es a mi rekordunk egyezese.
ALIASES = {
    # AX80, AX60, S900, S1000, MPC60 II, VX90: mind az Akai hangszeres vonala,
    # ami ma Akai Professional neven fut. A mi rekordunk Japan/1984.
    "Akai": "Akai Professional",
    # Model 600/700/800, Prophet-5, Pro One, Six-Trak: a ceg regi, teljes neve.
    "Sequential Circuits": "Sequential",
    # Csak Virus modellek, 1997-tol: pontosan a mi Access Music rekordunk.
    "Access": "Access Music",
    # The Cat, The Kitten, Voyetra 8: az Octave Electronics, kesobb
    # Octave-Plateau termekei, a mi rekordunk US/1975.
    "Octave": "Octave-Plateau",
    # Qasar M8 CMI, Fairlight I-III: a hangszer neve rakadt a markara.
    "Fairlight CMI": "Fairlight",
    # A GEM a Generalmusic sajat rovidites.
    "Generalmusic (GEM)": "Generalmusic",
    # LM-1, LinnDrum, Linn 9000: a Linn Electronics a ceg teljes neve.
    "Linn Electronics": "Linn",
    # MS6, MS800, MD-16: pontosan a Cheetah Marketing hangszerei.
    "Cheetah": "Cheetah Marketing",
    # Sonic V (muSonics) es Sonic Six (Moog). A muSonics 1971-ben vette meg az
    # R.A. Moogot, es a ket gep ugyanaz a konstrukcio ket nev alatt. A
    # queue_dupe_check 2026-09-02-en ezt a part EMBERI dontesre jelolte;
    # a dontes: a Moog rekord ala megy, mert a Sonic Six Moog-termekkent futott.
    "Moog muSonics": "Moog",
}

# Amit MEGNEZTUNK ES ELUTASITOTTUNK. Ezek valodi, kulon gyartok, nem nevalakok.
REJECTED = {
    "Elektronika": "Szovjet markanev (EM-04, EM-25, EM-26), semmi koze a sved Elektronhoz.",
    "KOMA Elektronik": "Berlini ceg (Field Kit, Komplex Sequencer), nem az Elektron.",
    "EMI": "Az Unost-21 szovjet hangszer, nem a holland Eminent.",
    "RMI": "Rocky Mount Instruments (Harmonic Synthesizer, 1974, USA), nem a rigai RMIF.",
}


def field(lines, label):
    for i, line in enumerate(lines):
        if line.strip() == label and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def cache_rows():
    """-> {markanev: [(model, url), ...]}, a halott oldalak nelkul."""
    out = {}
    for path in sorted(CACHE.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        text = d.get("text", "")
        if DEAD_MARK in text:
            continue
        lines = text.split("\n")
        brand, model = field(lines, "Brand"), field(lines, "Model")
        if brand and model:
            out.setdefault(brand, []).append((model, d["url"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows = cache_rows()
    total_new = 0
    for brand, canonical in ALIASES.items():
        hit = conn.execute(
            "SELECT id FROM manufacturers WHERE lower(canonical_name) = lower(?)",
            (canonical,)).fetchone()
        if not hit:
            print(f"  HIANYZO REKORD: {canonical} (a {brand} parja) -- kihagyva")
            continue
        mid = hit[0]
        models = rows.get(brand, [])
        new = []
        for model, url in models:
            exists = conn.execute(
                "SELECT 1 FROM instruments WHERE manufacturer_id = ? AND lower(name) = lower(?)",
                (mid, model)).fetchone()
            if not exists:
                new.append((model, url))
        print(f"  {brand:22s} -> {canonical:20s} cache {len(models):3d}, uj {len(new):3d}")
        if args.apply:
            for model, url in new:
                conn.execute(
                    "INSERT INTO instruments (manufacturer_id, name, source_url) VALUES (?, ?, ?)",
                    (mid, model, url))
        total_new += len(new)

    if args.apply:
        conn.commit()
        print(f"\nbeirva: {total_new} hangszer. Most futtasd: python3 db/read_synthdb_specs.py --ingest")
    else:
        print(f"\n{total_new} hangszer kerulne be. -- szarazfutas, --apply kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
