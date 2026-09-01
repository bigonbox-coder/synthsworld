#!/usr/bin/env python3
"""Gyártó- és hangszernevek a Wikidatából, szerkezetesen.

Nincs kulcs, nincs regisztráció, nincs botvédelem: nyilvános SPARQL végpont,
elég egy tisztességes User-Agent. Ezért volt érdemes megnézni.

MÉRSÉKELT VÁRAKOZÁS, és ezt előre kimondom, mert korábban túlígértem. Azt
mondtam Kristófnak, hogy ez egyedül több új nevet adna, mint az összes eddigi
forrásunk együtt. Megmérve ez NEM igaz: a Wikidata ebben a témában vékony, a
három lekérdezés együtt száz körüli gyártót és hangszert ad, nem ezreket. Amit
viszont ad, az tiszta: név, ország, alapítás éve, hivatalos honlap, és minden
nyelvű cikk linkje. A honlap külön értékes, mert az egyenesen a domain-mérőnek
való.

Három lekérdezés, mert egy nagy union időtúllépéssel elhal (mérve: 504).
Külön-külön mindegyik másodpercek alatt lefut.

A talált nevek a VÁRÓLISTÁRA kerülnek, nem a gyártók közé. A Wikidata sem
dönti el helyettünk, hogy egy név belefér-e a múzeum hatókörébe.

Használat:
  python3 db/harvest_wikidata.py --dry-run
  python3 db/harvest_wikidata.py --ingest
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "SynthsworldResearch/0.1 (synthsworld museum database; contact via kristof.gal@gmail.com)"

LABELS = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,hu,de,it,ja,ru". }'

QUERIES = {
    # 1. Ceg, aminek a TERMEKE elektronikus hangszer (vagy annak alosztalya).
    "termek": f"""SELECT DISTINCT ?item ?itemLabel ?countryLabel ?inception ?site WHERE {{
        ?item wdt:P1056 ?p . ?p wdt:P279* wd:Q1327500 .
        OPTIONAL {{ ?item wdt:P17 ?country }} OPTIONAL {{ ?item wdt:P571 ?inception }}
        OPTIONAL {{ ?item wdt:P856 ?site }}
        {LABELS} }} LIMIT 1500""",
    # 2. Ceg, aminek a termeke kifejezetten szintetizator.
    "szintetizator": f"""SELECT DISTINCT ?item ?itemLabel ?countryLabel ?inception ?site WHERE {{
        {{ ?item wdt:P1056 wd:Q163829 }} UNION {{ ?item wdt:P1056 wd:Q831698 }}
        UNION {{ ?item wdt:P1056 wd:Q320002 }} UNION {{ ?item wdt:P1056 wd:Q1327327 }}
        OPTIONAL {{ ?item wdt:P17 ?country }} OPTIONAL {{ ?item wdt:P571 ?inception }}
        OPTIONAL {{ ?item wdt:P856 ?site }}
        {LABELS} }} LIMIT 1500""",
}

# 3. A hangszerek fele indulva: minden elektronikus hangszer es a GYARTOJA. Ez
#    mas halmaz, mert a hangszerek jobban le vannak fedve mint a cegek.
Q_INSTRUMENTS = f"""SELECT DISTINCT ?maker ?makerLabel ?inst ?instLabel ?year WHERE {{
    ?inst wdt:P31/wdt:P279* wd:Q1327500 .
    ?inst wdt:P176 ?maker .
    OPTIONAL {{ ?inst wdt:P571 ?year }}
    {LABELS} }} LIMIT 3000"""


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def sparql(query, tries=3):
    url = f"{ENDPOINT}?query={urllib.parse.quote(query)}&format=json"
    for i in range(tries):
        r = subprocess.run(["curl", "-sSL", "--max-time", "90",
                            "-H", "Accept: application/sparql-results+json",
                            "-A", UA, url], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)["results"]["bindings"]
        except Exception:
            time.sleep(5 * (i + 1))
    print(f"  ! a lekerdezes nem jott ossze: {r.stdout[:120] if r.stdout else 'ures valasz'}")
    return []


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def label_is_qid(s):
    return bool(re.fullmatch(r"Q\d+", s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.ingest):
        ap.print_help()
        return

    makers = {}     # nev -> dict
    for name, q in QUERIES.items():
        rows = sparql(q)
        print(f"  {name}: {len(rows)} sor")
        for r in rows:
            lbl = r.get("itemLabel", {}).get("value", "").strip()
            if not lbl or label_is_qid(lbl):
                continue
            makers.setdefault(lbl, {
                "country": r.get("countryLabel", {}).get("value"),
                "inception": (r.get("inception", {}).get("value") or "")[:4] or None,
                "site": r.get("site", {}).get("value"),
            })
        time.sleep(2)

    rows = sparql(Q_INSTRUMENTS)
    print(f"  hangszer -> gyarto: {len(rows)} sor")
    instruments = []
    for r in rows:
        mk = r.get("makerLabel", {}).get("value", "").strip()
        inst = r.get("instLabel", {}).get("value", "").strip()
        if not mk or label_is_qid(mk):
            continue
        makers.setdefault(mk, {"country": None, "inception": None, "site": None})
        if inst and not label_is_qid(inst):
            instruments.append((mk, inst, (r.get("year", {}).get("value") or "")[:4] or None))

    con = sqlite3.connect(DB)
    known = {norm(r[0]) for r in con.execute("SELECT canonical_name FROM manufacturers")}
    known |= {norm(r[0]) for r in con.execute("SELECT manufacturer_name FROM discovery_queue")}
    known |= {norm(r[0]) for r in con.execute("SELECT name FROM manufacturer_name_history")}

    new = {k: v for k, v in makers.items() if norm(k) not in known}
    print(f"\n{len(makers)} gyarto a Wikidatabol, ebbol {len(new)} uj nekunk")
    for k in sorted(new)[:25]:
        v = new[k]
        print(f"    {k:38} {v['country'] or '':16} {v['inception'] or '':5} {v['site'] or ''}")
    if len(new) > 25:
        print(f"    ... es meg {len(new) - 25}")

    # A hivatalos honlapok egyenesen a domain-merőnek valok.
    sites = {urllib.parse.urlparse(v["site"]).netloc.lower()
             for v in makers.values() if v.get("site")}
    sites = {s for s in sites if s}
    have_dom = {r[0] for r in con.execute("SELECT domain FROM source_domains")}
    new_sites = sites - have_dom
    print(f"\n{len(sites)} hivatalos honlap, ebbol {len(new_sites)} uj domain a nyilvantartasnak")

    if not args.ingest:
        print("\n-- proba, semmi nem irodott --")
        return

    ts = now_iso()
    for k, v in sorted(new.items()):
        bits = [b for b in (v["country"], v["inception"]) if b]
        note = "Wikidata, 2026-09-01" + (f" ({', '.join(bits)})" if bits else "")
        con.execute("""INSERT INTO discovery_queue (manufacturer_name, status, notes,
                       created_at, updated_at) VALUES (?, 'found', ?, ?, ?)""",
                    (k, note, ts, ts))
    for d in sorted(new_sites):
        con.execute("INSERT OR IGNORE INTO source_domains (domain, note) VALUES (?, ?)",
                    (d, "gyarto hivatalos honlapja a Wikidatabol"))
    con.commit()
    print(f"\nbeirva: {len(new)} nev a varolistara, {len(new_sites)} domain a nyilvantartasba")


if __name__ == "__main__":
    main()
