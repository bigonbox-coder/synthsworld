#!/usr/bin/env python3
"""Dokumentum-archívumok: mappalistás oldalak, ahol a mappa a gyártó.

A második forrás-család. Az első a termékkatalógus volt (gyártói sitemap,
harvest_sitemap.py); ez az, ahol valaki évtizedek alatt összegyűjtött
szervizkönyveket, kapcsolási rajzokat és kézikönyveket, és egyszerűen kirakta
őket mappákba. A synfo egyetlen lapon sorolja fel őket, a synthfool viszont
valódi könyvtárszerkezetben, gyártónként és modellenként.

Kristóf kérése (2026-09-01): "Kell hogy tudjuk azt is mihez hol találunk majd
letölthető dokumentumot." Pontosan ezt csinálja: nem tölt le semmit, hanem
felírja, hogy melyik hangszerhez melyik címen van szervizkönyv vagy rajz.

TANULSÁG, amiért ez a script nem a sitemapból indul. A synthfool sitemapja egy
WordPress blogot ír le -- 69 bejegyzést a tulajdonos személyes jegyzeteivel --,
a VALÓDI archívum pedig a /docs/ alatt van, amiről a sitemap nem tud. Ha
megbízom a mérőben, egy blogot arattam volna le szervizkönyvek helyett. A
sitemap léte tehát azt mondja meg, hogy egy oldal gépi úton olvasható, nem azt,
hogy MI van rajta.

ILLEM. A synthfool robots.txt-je crawl-delay: 10-et kér, és ezt betartjuk. Emiatt
a mély bejárás lassú, tehát csak ritkán, kézzel futtatjuk (--full). Az
alapértelmezett futás csak a legfelső szintet nézi meg, az néhány kérés.

Használat:
  python3 db/harvest_docdir.py --source synthfool --dry-run
  python3 db/harvest_docdir.py --source synthfool --full --ingest
"""

import argparse
import html
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maker_lookup import MakerLookup  # noqa: E402

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = "SynthsworldResearch/0.1 (synthsworld museum database; contact kristof.gal@gmail.com)"

SOURCES = {
    "synthfool": {
        "root": "http://www.synthfool.com/docs/",
        "domain": "synthfool.com",
        "delay": 10,          # a robots.txt ennyit ker
        # mappanev -> a mi canonical nevunk, ahol elter
        "aliases": {
            "Arp": "ARP Instruments", "Paia": "PAiA Electronics, Inc.",
            "SequentialCircuits": "Sequential", "OctavePlateau": "Octave-Plateau",
            "Ppg": "PPG", "EML": "Electronic Music Laboratories",
            "Korg": "Korg Inc.", "Moog": "Moog Music", "Roland": "Roland Corporation",
            "Buchla": "Buchla Electronic Musical Instruments",
        },
        # nem gyarto-mappak
        "skip": {"Other_Misc", "ETI", "Marshall", "Leslie"},
    },
}

DOC_EXT = re.compile(r"\.(pdf|zip|jpe?g|gif|png|tiff?|doc|djvu)$", re.I)
DOC_WORDS = re.compile(
    r"[_\- ]?(service|schematic|schematics|manual|owners?|users?|guide|notes?|"
    r"addendum|parts|placement|operation|repair|sm|om)[_\- ]?", re.I)


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def get(url):
    r = subprocess.run(["curl", "-sSL", "--max-time", "45", "-A", UA, url],
                       capture_output=True, text=True, errors="replace")
    return r.stdout or ""


def listing(url):
    """-> (fajlok, almappak) egy konyvtar-listabol."""
    body = get(url)
    files, dirs = [], []
    for raw in re.findall(r'href=["\']([^"\']+)["\']', body, re.I):
        h = html.unescape(raw)
        if h.startswith(("http", "mailto", "?", "/", "#")) or h in ("../", ".."):
            continue
        (dirs if h.endswith("/") else files).append(h)
    return files, dirs


def model_from(filename, maker_folder):
    """'Moog_Sonic_Six_Service_Manual.pdf' -> 'Sonic Six'."""
    stem = urllib.parse.unquote(filename)
    stem = DOC_EXT.sub("", stem)
    stem = DOC_WORDS.sub(" ", stem)
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(rf"^\s*{re.escape(maker_folder)}\s*", "", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    return stem


def crawl(key, full):
    src = SOURCES[key]
    root = src["root"]
    delay = src["delay"]
    _, makers = listing(root)
    time.sleep(delay)
    out = []          # (maker_folder, model_hint, url)
    for folder in makers:
        name = folder.rstrip("/")
        if name in src["skip"]:
            continue
        url = urllib.parse.urljoin(root, folder)
        files, subs = listing(url)
        time.sleep(delay)
        for f in files:
            if DOC_EXT.search(f):
                out.append((name, model_from(f, name), urllib.parse.urljoin(url, f)))
        if not full:
            continue
        for sub in subs:
            surl = urllib.parse.urljoin(url, sub)
            sfiles, _ = listing(surl)
            time.sleep(delay)
            hint = urllib.parse.unquote(sub.rstrip("/")).replace("_", " ")
            for f in sfiles:
                if DOC_EXT.search(f):
                    out.append((name, hint, urllib.parse.urljoin(surl, f)))
        print(f"  {name}: {len(files)} fajl, {len(subs)} almappa")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), required=True)
    ap.add_argument("--full", action="store_true", help="a modell-almappakat is (lassu)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.ingest):
        ap.print_help()
        return

    src = SOURCES[args.source]
    rows = crawl(args.source, args.full)
    print(f"\n{len(rows)} dokumentum {len({r[0] for r in rows})} gyarto-mappaban")

    con = sqlite3.connect(DB)
    # A feloldas kozos (db/maker_lookup.py): rovid nev, hosszu ceg-alak es
    # nev-tortenet egyutt. A lenti aliases tabla a HOSSZU alakokra mutat, ami a
    # 2026-09-02-i nev-modell ota mar nem a canonical_name -- enelkul a Korg, a
    # Moog, a Roland, a Buchla es az EML mappaja csendben kimaradt.
    makers = MakerLookup(con)
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

    have = {r[0] for r in con.execute(
        "SELECT url FROM external_links WHERE source_name=?", (args.source,))}
    ts, new, unknown = now_iso(), 0, set()
    for folder, hint, url in rows:
        want = src["aliases"].get(folder, folder)
        mid = makers.find(want)
        if mid is None:
            unknown.add(folder)
            continue
        if url in have:
            continue
        idx = {norm(r[0]): r[1] for r in con.execute(
            "SELECT name, id FROM instruments WHERE manufacturer_id=?", (mid,))}
        iid = idx.get(norm(hint))
        label = f"{hint} dokumentum" if hint else "dokumentum"
        new += 1
        if args.ingest:
            con.execute(
                """INSERT INTO external_links (manufacturer_id, instrument_id, url, domain,
                   label, link_type, found_on, source_name, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (None if iid else mid, iid, url, src["domain"], label,
                 "service_mod", src["root"], args.source, "unchecked", ts))
    if args.ingest:
        con.execute("UPDATE source_domains SET harvester='harvest_docdir' WHERE domain=?",
                    (src["domain"],))
        con.commit()
    print(f"{new} uj link" + (" beirva" if args.ingest else " (proba, semmi nem irodott)"))
    if unknown:
        print(f"gyarto-mappa rekord nelkul ({len(unknown)}): {', '.join(sorted(unknown))}")


if __name__ == "__main__":
    main()
