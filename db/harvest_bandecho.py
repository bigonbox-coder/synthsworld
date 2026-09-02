#!/usr/bin/env python3
"""bandecho.de: nemet orchestergeraet-archivum -- kezikonyvek, katalogusok, kapcsolasi rajzok.

Kristof, 2026-09-02: "igen kell a leszedo."

HOGYAN TALALTUK
===============
Az Echolette (id 74) kutatasa kozben: a www.echolette.de HTTP 302-vel ide
iranyit at. Nem gyartoi oldal, hanem egy nemet gyujtoi-dokumentacios archivum
("Sammlung, Dokumentation und Instandsetzung von Musikelektronik der 50er- bis
80er Jahre"), tobb marka anyagaval.

Ez NEM hangszer-forras: termekoldal nincs benne, es a leirt keszulekek tulnyomo
resze erosito, hangfal, szalagecho. DOKUMENTUM-forras, es abbol nagyon jo: a
merés 1515 egyedi PDF-et talalt.

MIERT NEM KAPARAS
=================
A robots.txt csak a /wp-admin/-t tiltja. A dokumentumok sima <a href="...pdf">
hivatkozasok a szekcio-oldalakon, a PDF-ek pedig egyetlen hoston allnak
(download.bandecho.de). Nem kell sem fejes bongeszo, sem tobb ezer keres: a
menu 35 szekcio-oldala mindet felsorolja.

FIGYELEM, a sitemap NEM eleg: a wp-sitemap-posts-page-1.xml-bol HIANYZIK a
harom Vermona-oldal (handbuecher, kataloge, schaltplaene), pedig a menuben ott
vannak. Ezert a szekcio-listat a FOOLDAL MENUJEBOL vesszuk, nem a sitemapbol.

MARKA-FELISMERES, HAROM JELBOL
==============================
Az anchor szovege minden linken csak "Download", tehat hasznalhatatlan. A
markat es a modellt a FAJLNEV es az UT adja, ebben a sorrendben:

  1. Hans-Ohms archivum: .../Archiv_Hans_Ohms/<ev>/pdf/<Marka>/...
     (a "Vermona - Weltklang - Boehm" mappa harom markat jelol egyszerre, ezert
     az ilyen mappat nem soroljuk egyetlen markahoz, hanem ismeretlennek vesszuk)
  2. Fajlnev elso tagja: "Dynacord_Eminent_II_Handbuch.pdf" -> Dynacord
  3. A szekcio-oldal cime: .../handbuecher/hohner-handbuecher -> Hohner

Amelyik markat NEM ismerjuk (Schaller, Allsound, Solton, Stramp, Framus,
Suprem, Weltklang, Boehm), annak a linkjet NEM dobjuk el szo nelkul: a nevet
felvesszuk a discovery_queue-ba, mert az archivum meretebol itelve valodi
gyartok. A linkjuk viszont nem kerul be, amig nincs gyarto, akihez kossuk.

DOKUMENTUM-TIPUS
================
  handbuecher, schaltplaene, serviceunterlagen, reparatur -> service_mod
  minden mas (katalogusok, OGP, schriftgut, relikte, Hans-Ohms) -> archive

MODELL-HOZZAKOTES
=================
Ha a fajlnevben szerepel egy MAR MEGLEVO hangszerunk neve, a link ahhoz a
hangszerhez kotodik, kulonben a gyartohoz. A leghosszabb egyezo nev nyer, hogy
az "M120 A" ne az "M120"-hoz menjen.

Hasznalat:
    python3 db/harvest_bandecho.py --dry-run
    python3 db/harvest_bandecho.py --ingest
    python3 db/harvest_bandecho.py --dry-run --queue-unknown   # ismeretlen markak a varolistara
"""

import argparse
import html
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from maker_lookup import MakerLookup  # noqa: E402

DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "bandecho"
HOME = "https://bandecho.de/"
DOMAIN = "bandecho.de"
SOURCE = "bandecho"
UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")
DELAY = 1.2

# A fajlnev/ut elso tagjakent elofordulo marka-jeloltek. Csak a felismereshez
# kell: hogy a nevbol GYARTO lesz-e nalunk, azt a maker_lookup donti el.
BRAND_TOKENS = [
    "Dynacord", "Echolette", "Klemt", "Hohner", "Vermona", "Schaller",
    "Allsound", "Solton", "Stramp", "Framus", "Suprem", "Weltklang",
    "Boehm", "Bohm", "Rim", "Elka", "Wersi",
]
# A szekcio-oldal utolso utszakaszabol a marka.
SECTION_BRAND = {
    "echolette": "Echolette", "klemt-echolette": "Echolette",
    "dynacord": "Dynacord", "schaller": "Schaller",
    "hohner-handbuecher": "Hohner", "hohner-kataloge": "Hohner",
    "hohner-schaltplaene": "Hohner",
    "vermona-handbuecher": "Vermona", "vermona-kataloge": "Vermona",
    "vermona-schaltplaene": "Vermona",
    "allsound-handbuecher": "Allsound", "allsound-kataloge": "Allsound",
    "allsound-schaltplaene": "Allsound",
}
# Tobb markat egyszerre jelolo mappanev: nem lehet egyhez kotni.
MULTI_BRAND_DIR = re.compile(r"\s-\s")
# Mappa- es fajlnev-tagok, amik NEM markak. Az elso futas ezeket mind
# "markakent" hozta a Hans-Ohms ut szakaszaibol: evszamos almappa (2005), a
# gyujto neve maga (Archiv_Hans_Ohms), es temamappak (Technik, Mikros).
NOT_A_BRAND = {"technik", "archiv_hans_ohms", "mikros", "pdf", "last",
               "dokumente", "service", "manual", "schematics", "ogp"}
# Amit varolistara IS erdemes tenni: valodi hangszer- vagy
# zenei-elektronikai marka. A Tesla, Isophon es Telefunken szandekosan
# marad ki: hangszoro- es csogyartok, nem hangszergyartok.
QUEUE_WORTHY = {"Schaller", "Allsound", "Vermona", "Solton", "Stramp",
                "Framus", "Suprem", "Klemt", "Rim", "Weltklang", "Boehm"}
SERVICE_SECTIONS = ("handbuecher", "schaltplaene", "serviceunterlagen",
                    "reparatur-und-serviceberichte")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fetch(url):
    r = subprocess.run(["curl", "-sSL", "--max-time", "40", "-A", UA, url],
                       capture_output=True)
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""


def cached(url, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        body = fetch(url)
        if not body:
            return ""
        path.write_text(body, encoding="utf-8")
        time.sleep(DELAY)
    return path.read_text(encoding="utf-8")


def section_urls():
    """A fooldal menujebol, NEM a sitemapbol -- lasd a modul fejleceben."""
    home = cached(HOME, "index.html")
    urls = sorted(set(re.findall(
        r'href="(https://bandecho\.de/(?:dokumente|technik)[^"]*)"', home)))
    # A gyujto-oldalak (pl. /dokumente) is jonnek, azok ugysem adnak PDF-et.
    return urls


def slug(url):
    return urllib.parse.urlparse(url).path.strip("/").replace("/", "_") or "index"


def brand_of(pdf_url, section_slug):
    """(marka, honnan) vagy (None, ok). Harom jel, a fejlecben leirt sorrendben."""
    path = urllib.parse.unquote(urllib.parse.urlparse(pdf_url).path)
    segments = path.strip("/").split("/")
    name = segments[-1]

    if "Archiv_Hans_Ohms" in segments:
        folder = segments[-2] if len(segments) > 1 else ""
        if MULTI_BRAND_DIR.search(folder):
            return None, f"tobb marka egy mappaban: {folder}"
        if folder and folder.lower() not in NOT_A_BRAND and not folder.isdigit():
            return folder, "hans-ohms mappa"

    stem = re.split(r"[_\-]", name, maxsplit=1)[0]
    for token in BRAND_TOKENS:
        if stem.lower() == token.lower():
            return token, "fajlnev"

    last = section_slug.rsplit("_", 1)[-1]
    if last in SECTION_BRAND:
        return SECTION_BRAND[last], "szekcio"
    return None, "nincs marka-jel"


def link_type_of(section_slug):
    return "service_mod" if any(s in section_slug for s in SERVICE_SECTIONS) else "archive"


def label_of(pdf_url):
    name = urllib.parse.unquote(urllib.parse.urlparse(pdf_url).path).rsplit("/", 1)[-1]
    return re.sub(r"[_]+", " ", name[:-4]).strip()


def collect():
    """-> [{url, section, brand, brand_from, link_type, label}]  es a szekcio-statisztika"""
    out, per_section, seen = [], Counter(), set()
    sections = section_urls()
    print(f"{len(sections)} szekcio-oldal a menubol")
    for url in sections:
        s = slug(url)
        body = cached(url, f"{s}.html")
        if not body:
            print(f"  ! nem jott le: {url}")
            continue
        pdfs = re.findall(r'href="([^"]+\.pdf)"', body, re.I)
        for raw in pdfs:
            pdf = html.unescape(raw)
            if pdf in seen:
                continue
            seen.add(pdf)
            brand, why = brand_of(pdf, s)
            out.append({"url": pdf, "section": url, "brand": brand,
                        "brand_from": why, "link_type": link_type_of(s),
                        "label": label_of(pdf)})
            per_section[s] += 1
    return out, per_section


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--queue-unknown", action="store_true",
                    help="az ismeretlen markakat vegye fel a discovery_queue-ba")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    if not (args.ingest or args.dry_run):
        ap.print_help()
        return 0

    docs, per_section = collect()
    print(f"{len(docs)} egyedi PDF\n")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    ml = MakerLookup(con)

    by_brand = Counter(d["brand"] or "(ismeretlen)" for d in docs)
    known, unknown = {}, []
    for brand in sorted(by_brand):
        if brand == "(ismeretlen)":
            continue
        mid = ml.find(brand)
        if mid:
            known[brand] = mid
        else:
            unknown.append(brand)

    print("MARKA -> GYARTO")
    for brand, n in by_brand.most_common():
        if brand in known:
            r = con.execute("SELECT canonical_name FROM manufacturers WHERE id=?",
                            (known[brand],)).fetchone()
            print(f"  {n:5d}  {brand:<22} -> id={known[brand]} {r['canonical_name']}")
        else:
            print(f"  {n:5d}  {brand:<22} -- nincs ilyen gyartonk, a link NEM kerul be")

    # instrument-nev -> id, csak az erintett gyartokra
    inst = defaultdict(list)
    for mid in set(known.values()):
        for r in con.execute("SELECT id, name FROM instruments WHERE manufacturer_id=?", (mid,)):
            n = norm(r["name"])
            if len(n) >= 3:
                inst[mid].append((n, r["id"], r["name"]))
    for mid in inst:
        inst[mid].sort(key=lambda t: -len(t[0]))

    have = {r["url"] for r in con.execute(
        "SELECT url FROM external_links WHERE source_name=?", (SOURCE,))}

    rows, matched = [], 0
    for d in docs:
        mid = known.get(d["brand"])
        if not mid or d["url"] in have:
            continue
        key = norm(d["label"])
        iid = None
        for n, i, _name in inst.get(mid, []):
            if n in key:
                iid = i
                matched += 1
                break
        rows.append((None if iid else mid, iid, d["url"], DOMAIN, d["label"],
                     d["link_type"], d["section"], SOURCE, "unchecked"))

    kinds = Counter(r[5] for r in rows)
    print(f"\n{len(rows)} uj link keszen all ({dict(kinds)}), ebbol {matched} kotheto hangszerhez")
    if unknown:
        worthy = [b for b in unknown if b in QUEUE_WORTHY]
        rest = [b for b in unknown if b not in QUEUE_WORTHY]
        print(f"\nISMERETLEN MARKA ({len(unknown)}). Varolistara valo ({len(worthy)}):")
        print("   " + ", ".join(worthy))
        if rest:
            print(f"   varolistara NEM valo ({len(rest)}): " + ", ".join(rest))
    nobrand = [d for d in docs if not d["brand"]]
    if nobrand:
        print(f"\n{len(nobrand)} PDF-nel nem allapithato meg a marka, ezek kimaradnak. Peldak:")
        for d in nobrand[:5]:
            print(f"    {d['label'][:60]}  ({d['brand_from']})")

    if not args.ingest:
        print("\n-- szarazfutas, semmi nem irodott. --ingest kell hozza --")
        return 0

    ts = now_iso()
    con.executemany(
        """INSERT INTO external_links (manufacturer_id, instrument_id, url, domain,
           label, link_type, found_on, source_name, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""", [r + (ts,) for r in rows])
    queued = 0
    if args.queue_unknown:
        for brand in [b for b in unknown if b in QUEUE_WORTHY]:
            ex = con.execute("SELECT id FROM discovery_queue WHERE lower(manufacturer_name)=lower(?)",
                             (brand,)).fetchone()
            if ex:
                continue
            queued += 1
            con.execute(
                "INSERT INTO discovery_queue (manufacturer_name, status, notes, created_at) "
                "VALUES (?, 'found', ?, ?)",
                (brand, f"[{ts[:10]}] bandecho.de dokumentum-archivum: "
                        f"{by_brand[brand]} sajat PDF (kezikonyv, katalogus vagy kapcsolasi rajz). "
                        f"Nemet/NDK orchestergeraet-kor. Meg nincs gyarto-rekordja nalunk.", ts))
    con.execute("UPDATE source_domains SET harvester='harvest_bandecho', harvested_at=? "
                "WHERE domain=?", (ts, DOMAIN))
    con.commit()
    print(f"\nbeirva: {len(rows)} link" + (f", {queued} uj varolistas nev" if args.queue_unknown else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
