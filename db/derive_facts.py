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

# Ugyanaz hangszer-sorra. Kulon nevvel, mert a keret a ket tipust MAS tablaba
# irja (facts_sources kontra instrument_facts_sources), es egy elgepelt mezo
# igy nem a masik tablara epitene az SQL-t.
DerivedInstrumentFact = namedtuple("DerivedInstrumentFact",
                                   "instrument_id field_name value source_url source_tier derived_from")


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



def rule_technology_from_oscillators(conn, verbose=True):
    """A hangszer technologiaja, ha az oszcillator-leiras KIMONDJA.

    Kristof, 2026-09-04: "kitoltheted ami igazolt." Ez a szabaly nem
    kovetkeztet, hanem olvas: az instrument_specs 'oscillators' mezojeben a
    forras sajat szavai allnak nyersen ("Digital FM synthesizer with 6
    Operators", "1 VCO with Saw or Square waveforms"). Ha ott szerepel a
    "Digital", "FM operator", "AWM", "PCM" vagy a "sample ROM", akkor a forras
    kimondta, hogy digitalis. Ha a "VCO" szerepel, akkor kimondta, hogy analog.
    Ha mindketto, akkor hibrid. Ha egyik sem, a szabaly HALLGAT.

    MERES, 2026-09-04 (ezert szabad futnia):
      513 hangszernek van 'oscillators' spec-je, ebbol 198-nak MAR ismert a
      technologiaja. Azon a 198-on a szabaly 95 esetben nyilatkozott, es
      MIND A 95 egyezett a mar rogzitett ertekkel. Tevedes: 0. A maradek 103
      esetben hallgatott. A 315 ismeretlenbol 119-et tolt ki.

    MIERT NINCS BENNE A DCO:
      A digitally controlled oscillator digitalisan VEZERELT, de analog
      jelutu. A Juno-106 vagy a Matrix-6 DCO-s es kozben analog gep. A
      "digital" szo ott a vezerlesre vonatkozik, nem a hangkeltesre, ezert a
      DCO-t a szabaly szandekosan nem ismeri fel, es az ilyen sorok
      ismeretlenek maradnak, amig ember vagy jobb forras nem dont.

    A szabaly a mar kitoltott technologiat SOSEM irja felul (apply_instrument_fact),
    es minden irt sor melle megy egy instrument_facts_sources sor a
    derived_from nyommal, tehat az egesz termes egyetlen lekerdezessel
    azonosithato es visszavonhato.
    """
    import re as _re
    # Kimondottan DIGITALIS hangkeltes.
    DIG = _re.compile(r"\b(digital|FM operator|operators?\b.*\bFM|FM\b.*\boperators?|AWM|AFM|PCM|"
                      r"sample ROM|ROM sample|wave ?table ROM|8-bit|12-bit|16-bit|24-bit)\b", _re.I)
    # Kimondottan ANALOG hangkeltes.
    # CSAK a VCO. Az "analog oscillator" kifejezes NEM kerult ide, pedig
    # kezenfekvo lenne: 2026-09-04-en megmerve a Roland JD-XA es a Novation
    # Ultranova is igy irja le magat, kozben mindketto digitalis, illetve
    # virtualis-analog gep. A kifejezes tehat nem bizonyit, ezert lent, az
    # AMBIG listaban all: ha ez a szo szerepel, a szabaly HALLGAT.
    ANA = _re.compile(r"\b(VCO|VCOs)\b", _re.I)
    # AMI MIATT HALLGATNI KELL. Ezek a szavak azt jelzik, hogy a ket vilag
    # keveredik, es a mezobol NEM lehet eldonteni, melyik a hangkelto ut:
    #   DCO        digitalisan vezerelt, de ANALOG jelut (Juno-106, OSCar, Evolver)
    #   modeling   digitalis emulacio, ami analog nevet visel (Nord, V-Synth,
    #              Novation Drum Station: "Digital Analog Sound Modeling")
    #   RCO        digitalis hullam analog oszcillator mellett (JoMoX SunSyn)
    # 2026-09-04-i meres: e nelkul a szuro nelkul a szabaly 119 sorbol 12-t
    # rontott el, es MIND A 12 ilyen kevert eset volt.
    AMBIG = _re.compile(r"\b(DCO|DCOs|RCO|RCOs|model+ing|modell?ed|emulat|"
                        r"analog(ue)?\s+oscillators?)", _re.I)

    # DIGITALIS ARULKODO JEL MAS MEZOBOL. A Novation Ultranova oszcillator-sora
    # szo szerint "3 VCOs", pedig virtualis-analog gep: a vintagesynth egyszeruen
    # VCO-nak hivja a modellezett oszcillatort is. Egyetlen mezobol ezt nem lehet
    # eszrevenni, a szomszedos mezokbol viszont igen: ott a "ROM" hullamforma es
    # a ROM-patch memoria. Ezert az ANALOG verdikt elott megnezzuk, mond-e a
    # tobbi spec valami olyat, amit csak digitalis gep tud.
    tells = set()
    try:
        for tr in conn.execute(
                "SELECT DISTINCT instrument_id FROM instrument_specs WHERE "
                "field IN ('sample_rate', 'rom_size') "
                "OR (field IN ('waveforms', 'memory') AND (value LIKE '%ROM%' "
                "    OR value LIKE '%wavetable%' OR value LIKE '%sample%'))").fetchall():
            tells.add(tr[0])
    except Exception:
        tells = set()

    rows = conn.execute(
        "SELECT s.instrument_id, s.value, s.source_url, s.source_name, i.name, i.technology "
        "FROM instrument_specs s JOIN instruments i ON i.id = s.instrument_id "
        "WHERE s.field = 'oscillators' AND s.value IS NOT NULL AND s.value != '' "
        "  AND (i.technology IS NULL OR i.technology = 'unknown') "
        "ORDER BY i.name").fetchall()
    if verbose:
        print(f"technology_from_oscillators: {len(rows)} ismeretlen technologiaju "
              f"hangszernek van oszcillator-leirasa")

    out, silent = [], 0
    for r in rows:
        v = r["value"]
        if AMBIG.search(v):
            silent += 1
            continue
        d, a = bool(DIG.search(v)), bool(ANA.search(v))
        # Ha MINDKETTO ott van, a mezo nem dont el semmit: hallgatunk. A regi
        # valtozat itt "hybrid"-et irt, es ez volt a hibak masik fele.
        if d and a:
            silent += 1
            continue
        tech = "digital" if d else ("analog" if a else None)
        if tech is None:
            silent += 1
            continue
        if tech == "analog" and r["instrument_id"] in tells:
            silent += 1
            continue
        out.append(DerivedInstrumentFact(
            instrument_id=r["instrument_id"], field_name="technology", value=tech,
            source_url=r["source_url"], source_tier="other",
            derived_from=f"technology_from_oscillators: oscillators={v[:120]}"))
    if verbose:
        print(f"  kimondja: {len(out)}, hallgat: {silent}")
    return out


RULES = {
    "city_to_country": rule_city_to_country,
    "technology_from_oscillators": rule_technology_from_oscillators,
}


# ------------------------------------------------------------------- keret

def is_instrument_fact(fact):
    return isinstance(fact, DerivedInstrumentFact)


def already_recorded(conn, fact):
    """Ne irjuk be ketszer ugyanazt: a szabaly nyoma a kulcs."""
    if is_instrument_fact(fact):
        return conn.execute(
            "SELECT 1 FROM instrument_facts_sources WHERE instrument_id = ? "
            "AND field_name = ? AND derived_from = ?",
            (fact.instrument_id, fact.field_name, fact.derived_from)).fetchone() is not None
    return conn.execute(
        "SELECT 1 FROM facts_sources WHERE manufacturer_id = ? AND field_name = ? "
        "AND derived_from = ?",
        (fact.manufacturer_id, fact.field_name, fact.derived_from)).fetchone() is not None


# Amit egy szabaly egyaltalan kitolthet. Kifejezett lista, mert egy elgepelt
# mezonev kulonben SQL-t epitene a manufacturers tablara.
WRITABLE_FIELDS = {"country", "city", "founded_year", "ended_year",
                   "official_website", "founders", "entity_type"}

# Ugyanez hangszer-sorra. A technology kotott ertekkeszletu a semaban
# (analog/digital/hybrid/unknown), ezert az ures mezo itt 'unknown', nem NULL:
# a feltetel ezt kulon kezeli, kulonben a szabaly sose irna semmit.
WRITABLE_INSTRUMENT_FIELDS = {"technology", "year", "category"}
EMPTY_IS_UNKNOWN = {"technology"}


def apply_instrument_fact(conn, fact):
    """Ugyanaz a szabaly hangszer-sorra: csak ures mezot tolt ki."""
    if fact.field_name not in WRITABLE_INSTRUMENT_FIELDS:
        raise ValueError(f"a(z) {fact.field_name} hangszer-mezot szabaly nem irhatja "
                         f"(vedd fel a WRITABLE_INSTRUMENT_FIELDS-be, ha tenyleg kell)")
    col = fact.field_name
    empty = f"({col} IS NULL OR {col} = '')"
    if col in EMPTY_IS_UNKNOWN:
        empty = f"({col} IS NULL OR {col} = '' OR {col} = 'unknown')"
    cur = conn.execute(
        f"UPDATE instruments SET {col} = ? WHERE id = ? AND {empty}",
        (fact.value, fact.instrument_id))
    conn.execute(
        "INSERT INTO instrument_facts_sources (instrument_id, field_name, value, "
        "source_url, source_tier, fetched_at, derived_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fact.instrument_id, fact.field_name, fact.value, fact.source_url,
         fact.source_tier, now_iso(), fact.derived_from))
    return cur.rowcount


def apply_fact(conn, fact):
    """A mezot csak akkor toltjuk ki, ha meg ures. A levezetes nem elozi meg a
    kimondott tenyt, csak potolja a hianyat."""
    if is_instrument_fact(fact):
        return apply_instrument_fact(conn, fact)
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


def show_proposals(conn):
    """A javaslatok allapota. A dontesre varok legfelul, mert azok az enyeim."""
    order = {"proposed": 0, "approved": 1, "implemented": 2, "rejected": 3}
    rows = sorted(conn.execute("SELECT * FROM derivation_rule_proposals"),
                  key=lambda r: (order.get(r["status"], 9), r["rule_name"]))
    if not rows:
        print("nincs egyetlen szabaly-javaslat sem")
        return 0
    for r in rows:
        print(f"\n[{r['status']}] {r['rule_name']}")
        print(f"  {r['description']}")
        if r["evidence"]:
            print(f"  bizonyitek: {r['evidence']}")
        if r["affects"]:
            print(f"  erintene:   {r['affects']}")
        if r["note"]:
            print(f"  megjegyzes: {r['note']}")
    pending = sum(1 for r in rows if r["status"] == "proposed")
    print(f"\n{len(rows)} javaslat, ebbol {pending} var dontesre")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--rule", action="append", help="csak ezt a szabalyt futtassa")
    ap.add_argument("--proposals", action="store_true",
                    help="a szabaly-javaslatok listaja, futtatas nelkul")
    ap.add_argument("--propose", nargs=2, metavar=("NEV", "LEIRAS"),
                    help="uj szabaly-javaslat felvetele")
    ap.add_argument("--evidence", help="--propose melle: a mert bizonyitek")
    ap.add_argument("--affects", help="--propose melle: hany rekordot erintene")
    ap.add_argument("--decide", nargs=2, metavar=("NEV", "ALLAPOT"),
                    help="dontes: approved | rejected | implemented")
    ap.add_argument("--note", help="--decide melle: miert")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if args.propose:
        conn.execute(
            "INSERT OR REPLACE INTO derivation_rule_proposals "
            "(rule_name, description, evidence, affects, status) "
            "VALUES (?, ?, ?, ?, 'proposed')",
            (args.propose[0], args.propose[1], args.evidence, args.affects))
        conn.commit()
        print(f"felveve: {args.propose[0]} (dontesre var)")
        return 0

    if args.decide:
        name, status = args.decide
        if status not in ("approved", "rejected", "implemented"):
            print("az allapot csak approved, rejected vagy implemented lehet")
            return 2
        cur = conn.execute(
            "UPDATE derivation_rule_proposals SET status = ?, note = ?, decided_at = ? "
            "WHERE rule_name = ?", (status, args.note, now_iso(), name))
        conn.commit()
        print(f"{name}: {status}" if cur.rowcount else f"nincs ilyen javaslat: {name}")
        return 0 if cur.rowcount else 1

    if args.proposals:
        return show_proposals(conn)

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
