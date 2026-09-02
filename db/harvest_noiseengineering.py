#!/usr/bin/env python3
"""noiseengineering.us: eurorack modulok es manualjaik, a sajat page-data JSON-jukbol.

Kristof, 2026-09-02: "keszitsd el a leszedot hozza."

MIERT KELLETT SAJAT LESZEDO
===========================
A gyarto katalogusa JavaScriptbol renderelodik: a /collections/modules/ oldal
HTML-jeben mindossze 9 termek latszik a 125-bol. A cim (slug) pedig nem arulja
el, hogy hardver modul, gitarpedal vagy szoftver plugin -- Kristof
hardver-elsobbsege mellett viszont EPPEN ez a kerdes.

A megoldas nem kaparas: az oldal Gatsby-vel keszult, es minden termekhez kiad
egy strukturalt JSON-t (a sajat sitemapja sorolja fel a termekeket):

    https://noiseengineering.us/sitemap-0.xml
    https://noiseengineering.us/page-data/products/<slug>/page-data.json

A robots.txt semmit nem tilt (Disallow ures).

A BESOROLAS MERT, NEM TALALGATOTT
=================================
Meres mind a 125 terken (2026-09-02):

    productType:  Legacy Hardware 43, Hardware 42, Software 11, Firmware 10,
                  Sample Pack 8, Reason 5, Panel 3, Case 1, Apparel 1,
                  Free Software 1

A 85 hardver termekbol 82-nek van ModularGrid-hivatkozasa a sajat adatlapjan,
haromnak nincs -- es pont az a harom NEM modul: a Batverb es a Dystorpia
gitarpedal ("Made for guitars"), a Bee-Stock pedig B-aruas ajanlat, nem modell.
Tehat a ModularGrid-mezo megléte a gyarto SAJAT jelzese arrol, hogy eurorack
modulrol van szo.

    hardver + ModularGrid  -> eurorack modul, bekerul (category='module')
    hardver ModularGrid nelkul -> NEM kerul be, kilistazva emberi dontesre
    Firmware               -> kimarad: ugyanannak a fizikai modulnak (Versio,
                              Alia, Legio) a masik szoftvere, nem uj hangszer
    Software / Reason / Free Software / Sample Pack -> kimarad (Kristof: a
                              szoftver kesobbi kort kap)
    Panel / Case / Apparel -> kimarad, tartozek

EVSZAM NINCS. A termek-JSON nem ad megjelenesi datumot, es nem talalgatunk.

A cache (db/cache/noiseengineering/) miatt az ujrafuttatas halozat nelkul is
megy, es a mar meglevo oldalakat nem kerdezi ujra.

Hasznalat:
    python3 db/harvest_noiseengineering.py --dry-run
    python3 db/harvest_noiseengineering.py --ingest
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from maker_lookup import MakerLookup  # noqa: E402

DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "noiseengineering"
SITEMAP = "https://noiseengineering.us/sitemap-0.xml"
PAGE_DATA = "https://noiseengineering.us/page-data/products/{slug}/page-data.json"
PRODUCT_URL = "https://noiseengineering.us/products/{slug}/"
MAKER = "Noise Engineering"
UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")
DELAY = 1.0
HARDWARE = {"Hardware", "Legacy Hardware"}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fetch(url):
    r = subprocess.run(["curl", "-sS", "--max-time", "30", "-A", UA, "-L", url],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else b""


def product_slugs():
    xml = fetch(SITEMAP).decode("utf-8", errors="replace")
    return sorted(set(re.findall(
        r"<loc>https://noiseengineering\.us/products/([a-z0-9\-]+)/</loc>", xml)))


def load_products(slugs):
    """-> [{slug, title, productType, tags, modulargrid, manual_link}]"""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for i, slug in enumerate(slugs, 1):
        path = CACHE / f"{slug}.json"
        if not path.exists():
            body = fetch(PAGE_DATA.format(slug=slug))
            if not body:
                print(f"  ! nem jott le: {slug}")
                continue
            path.write_bytes(body)
            time.sleep(DELAY)
        try:
            p = json.loads(path.read_text(encoding="utf-8"))["result"]["data"]["neProduct"]
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f"  ! ertelmezhetetlen: {slug}")
            continue
        out.append({"slug": slug, "title": (p.get("title") or "").strip(),
                    "productType": p.get("productType"), "tags": p.get("tags") or [],
                    "modulargrid": p.get("modulargrid"),
                    "manual_link": p.get("manual_link")})
        if i % 25 == 0:
            print(f"  {i}/{len(slugs)}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="irjon is, ne csak mutasson")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    if not (args.ingest or args.dry_run):
        ap.print_help()
        return 0

    slugs = product_slugs()
    if not slugs:
        print("! a sitemap nem jott le")
        return 1
    print(f"{len(slugs)} termek a sitemapban")
    products = load_products(slugs)
    kinds = Counter(p["productType"] for p in products)
    print(f"productType: {dict(kinds)}")

    modules, unclear = [], []
    for p in products:
        if p["productType"] not in HARDWARE:
            continue
        (modules if p["modulargrid"] else unclear).append(p)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    mid = MakerLookup(con).find(MAKER)
    if mid is None:
        print(f"! nincs ilyen gyarto a tablaban: {MAKER}")
        return 1
    have = {r["name"].strip().lower() for r in con.execute(
        "SELECT name FROM instruments WHERE manufacturer_id=?", (mid,))}
    have_links = {r["url"] for r in con.execute(
        "SELECT url FROM external_links WHERE source_name='noiseengineering'")}

    new = [p for p in modules if p["title"].lower() not in have]
    manuals = [p for p in modules if p["manual_link"] and p["manual_link"] not in have_links]

    print(f"\n{len(modules)} eurorack modul (hardver + ModularGrid-hivatkozas)")
    print(f"  ebbol UJ nekunk: {len(new)}")
    print(f"{len(manuals)} uj manual-link")
    print(f"\n{len(unclear)} hardver ModularGrid NELKUL -- NEM kerul be, ember dontse el:")
    for p in unclear:
        print(f"    {p['title']}  ({p['productType']})  {PRODUCT_URL.format(slug=p['slug'])}")

    if not args.ingest:
        print("\n-- szarazfutas, semmi nem irodott. --ingest kell hozza --")
        return 0

    ts = now_iso()
    for p in new:
        con.execute(
            "INSERT INTO instruments (manufacturer_id, name, year, category, source_url, created_at) "
            "VALUES (?, ?, NULL, 'module', ?, ?)",
            (mid, p["title"], PRODUCT_URL.format(slug=p["slug"]), ts))
    inst_id = {r["name"].strip().lower(): r["id"] for r in con.execute(
        "SELECT id, name FROM instruments WHERE manufacturer_id=?", (mid,))}
    for p in manuals:
        iid = inst_id.get(p["title"].lower())
        con.execute(
            """INSERT INTO external_links (manufacturer_id, instrument_id, url, domain,
               label, link_type, found_on, source_name, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (None if iid else mid, iid, p["manual_link"], "noiseengineering.us",
             f"{p['title']} manual", "service_mod",
             PRODUCT_URL.format(slug=p["slug"]), "noiseengineering", "unchecked", ts))
    con.execute("UPDATE source_domains SET harvester='harvest_noiseengineering', "
                "harvested_at=? WHERE domain='noiseengineering.us'", (ts,))
    con.commit()
    print(f"\nbeirva: {len(new)} modul, {len(manuals)} manual-link")
    return 0


if __name__ == "__main__":
    sys.exit(main())
