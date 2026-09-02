#!/usr/bin/env python3
"""Levezetett tények: amit a forrás nem mondott ki, de gépiesen következik.

MIÉRT VAN EZ A SCRIPT
=====================
A kiolvasó lépés szabálya szigorú és marad is: a modell CSAK azt írhatja le,
amit a forrás kimond, minden más null. Enélkül elkezd kitalálni, és egy
kitalált évszám többet ront, mint amennyit egy üres mező.

Csakhogy ettől a szabálytól maradnak ott olyan lyukak, amiket nem is kellene
lyukként hagyni. Kristóf a Steiner-Parkeren vette észre, 2026-09-02: a cikk
soha nem írja le, hogy a cég amerikai, csak azt, hogy Salt Lake City-i. A
kiolvasó ezért helyesen hagyta üresen az országot. De hogy Salt Lake City az
Egyesült Államokban van, az nem vélemény és nem tipp.

Ez a script a KIMONDOTT tényekből vezet le továbbiakat, nevesített szabályok
szerint. Nem modell csinálja, hanem lekérdezés, tehát:
  * nulla modellhasználat, ütemezetten is futhat,
  * a végeredménynek van forrás-URL-je (a Wikidata-entitásé),
  * és a `facts_sources.derived_from` mező elárulja, MELYIK szabály és MILYEN
    bemenet adta, tehát egy rossz szabály egész termése visszavonható.

Ha bizonytalan, NEM dönt. Ha egy városnévhez két ország tartozik, kihagyja és
jelenti. A jelentés a lényeg: abból derül ki, hol kell egy új szabály.

ÚJ SZABÁLY HOZZÁADÁSA
=====================
Írj egy függvényt, ami egy gyártó-sorra vagy None-t ad, vagy egy
DerivedFact-et, és vedd fel a RULES listába. Ennyi. A keretrendszer intézi a
szárazfutást, a duplikátum-szűrést, a forrás-rögzítést és a jelentést.

Használat:
    python3 db/derive_facts.py              # szárazon, csak megmutatja
    python3 db/derive_facts.py --apply      # ír is
    python3 db/derive_facts.py --rule city_to_country --apply
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")

# mit vezettunk le | a gyarto id-je | a mezo | az ertek | a forras | a szabaly nyoma
DerivedFact = namedtuple("DerivedFact",
                         "manufacturer_id field_name value source_url source_tier derived_from")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sparql(query, tries=3):
    url = f"{ENDPOINT}?query={urllib.parse.quote(query)}&format=json"
    last = ""
    for i in range(tries):
        r = subprocess.run(["curl", "-sSL", "--max-time", "90",
                            "-H", "Accept: application/sparql-results+json",
                            "-A", UA, url], capture_output=True, text=True)
        last = r.stdout
        try:
            return json.loads(r.stdout)["results"]["bindings"]
        except Exception:
            time.sleep(5 * (i + 1))
    print(f"  ! a lekerdezes nem jott ossze: {last[:120] if last else 'ures valasz'}")
    return None


# ---------------------------------------------------------------- szabalyok

def rule_city_to_country(conn, verbose=True):
    """Van varos, nincs orszag -> a Wikidata megmondja, melyik orszagban van.

    Csak akkor ir, ha a varosnevhez PONTOSAN EGY orszag tartozik. Ha ketto
    (Cambridge, Birmingham, San Jose es tarsaik), akkor kihagyja: egy
    tobbertelmu nevbol orszagot valasztani mar tippeles lenne.
    """
    rows = conn.execute(
        "SELECT id, canonical_name, city FROM manufacturers "
        "WHERE (country IS NULL OR country = '') AND city IS NOT NULL AND city != '' "
        "ORDER BY canonical_name"
    ).fetchall()
    if verbose:
        print(f"city_to_country: {len(rows)} gyarto, akinek van varosa de nincs orszaga")

    out, skipped = [], []
    for r in rows:
        city = r["city"].strip()
        q = ('SELECT DISTINCT ?place ?country ?countryLabel WHERE { '
             f'?place rdfs:label "{city}"@en . '
             '?place wdt:P31/wdt:P279* wd:Q486972 . '
             '?place wdt:P17 ?country . '
             'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }')
        res = sparql(q)
        time.sleep(1.5)
        if res is None:
            skipped.append((r["canonical_name"], city, "a lekerdezes elhalt"))
            continue
        countries = {}
        for b in res:
            label = b.get("countryLabel", {}).get("value")
            place = b.get("place", {}).get("value")
            if label:
                countries.setdefault(label, place)
        if not countries:
            skipped.append((r["canonical_name"], city, "a Wikidata nem ismeri ezt a varost"))
            continue
        if len(countries) > 1:
            skipped.append((r["canonical_name"], city,
                            "tobbertelmu varosnev: " + ", ".join(sorted(countries))))
            continue
        label, place = next(iter(countries.items()))
        out.append(DerivedFact(
            manufacturer_id=r["id"], field_name="country", value=label,
            source_url=place, source_tier="wikidata",
            derived_from=f"city_to_country: city={city}"))
        if verbose:
            print(f"  {r['canonical_name']:28s} {city:22s} -> {label}")

    if verbose and skipped:
        print("  kihagyva (szandekosan, nem tippelunk):")
        for name, city, why in skipped:
            print(f"    {name:26s} {city:20s} {why}")
    return out


RULES = {
    "city_to_country": rule_city_to_country,
}


# ------------------------------------------------------------------- keret

def already_recorded(conn, fact):
    """Ne irjuk be ketszer ugyanazt: a szabaly nyoma a kulcs."""
    return conn.execute(
        "SELECT 1 FROM facts_sources WHERE manufacturer_id = ? AND field_name = ? "
        "AND derived_from = ?",
        (fact.manufacturer_id, fact.field_name, fact.derived_from)).fetchone() is not None


# Amit egy szabaly egyaltalan kitolthet. Kifejezett lista, mert egy elgepelt
# mezonev kulonben SQL-t epitene a manufacturers tablara.
WRITABLE_FIELDS = {"country", "city", "founded_year", "ended_year",
                   "official_website", "founders", "entity_type"}


def apply_fact(conn, fact):
    """A mezot csak akkor toltjuk ki, ha meg ures. A levezetes nem elozi meg a
    kimondott tenyt, csak potolja a hianyat."""
    if fact.field_name not in WRITABLE_FIELDS:
        raise ValueError(f"a(z) {fact.field_name} mezot szabaly nem irhatja "
                         f"(vedd fel a WRITABLE_FIELDS-be, ha tenyleg kell)")
    col = fact.field_name
    cur = conn.execute(
        f"UPDATE manufacturers SET {col} = ?, updated_at = ? "
        f"WHERE id = ? AND ({col} IS NULL OR {col} = '')",
        (fact.value, now_iso(), fact.manufacturer_id))
    conn.execute(
        "INSERT INTO facts_sources (manufacturer_id, field_name, value, source_url, "
        "source_tier, fetched_at, derived_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fact.manufacturer_id, fact.field_name, fact.value, fact.source_url,
         fact.source_tier, now_iso(), fact.derived_from))
    return cur.rowcount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--rule", action="append", help="csak ezt a szabalyt futtassa")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    names = args.rule or list(RULES)
    unknown = [n for n in names if n not in RULES]
    if unknown:
        print("ismeretlen szabaly: " + ", ".join(unknown))
        print("elerheto: " + ", ".join(RULES))
        return 2

    total_new = total_written = 0
    for name in names:
        print(f"\n== {name} ==")
        facts = RULES[name](conn)
        fresh = [f for f in facts if not already_recorded(conn, f)]
        total_new += len(fresh)
        if not args.apply:
            continue
        for f in fresh:
            total_written += apply_fact(conn, f)
        conn.commit()

    print()
    if args.apply:
        print(f"{total_new} uj levezetett teny, ebbol {total_written} mezot toltott ki")
        print("(a kulonbseg olyan teny, aminek a mezoje idokozben mar nem volt ures)")
    else:
        print(f"{total_new} uj levezetett teny szuletne")
        print("-- szarazfutas, semmi nem irodott. --apply kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
