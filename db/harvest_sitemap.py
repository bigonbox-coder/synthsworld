#!/usr/bin/env python3
"""Egy leszedő a gyártói honlapok CSALÁDJÁRA, nem oldalanként külön.

Kristóf, 2026-09-01: "a leszedőszkriptnél vedd figyelembe hogy ne oldalanként
legyen hanem optimalizált". Így is van, és ez önkritika is: a synfo és a
synthxl leszedője nyolcvan százalékban ugyanaz, mert a második írásakor még nem
látszott, hogy egy családról van szó.

A család ismertetőjele: a gyártó kiadja a sitemapját, a termékcímben ott a
modell, és az útvonalban ott a kategória. A Casio és a Yamaha pontosan ilyen, és
a mérés szerint a legtöbb gyártói honlap is az lesz. Egy új forrás bekötése így
nem új script, hanem egy bejegyzés a SOURCES-ban.

MIT ÍR ÉS MIT NEM. Modellneveket ír, a gyártó SAJÁT sitemapjából, forrás-URL-lel
-- ez owner-tier tény arról, hogy a modell létezik. Évszámot NEM ír, mert a
sitemap nem tartalmaz olyat, és tippelni rosszabb az üres mezőnél. Kategóriát
csak ott ír, ahol a forrás útvonala EGYÉRTELMŰEN megfeleltethető: a
`keyboards/synthesizers` az Keyboard - Synthesizer, ehhez nem kell megérteni
semmit. Ahol az útvonal kétértelmű (a Yamaha silent-piano akusztikus zongora
elektronikával), ott a kategória üresen marad, és az a feldolgozás dolga.

SCOPE. A gyártók sok mindent árulnak. A Yamaha fúvósokat, vonósokat, akusztikus
ütőket és gitárokat is, azok Kristóf hangkeltés-tesztje szerint kiesnek. Ezért
minden forráshoz tartozik egy engedélyezett alkategória-lista: ami nincs rajta,
az be sem jön. Ez a "forrásonként egy beállítás", és ez a szűrő tartja tisztán a
bázist.

Használat:
  python3 db/harvest_sitemap.py --list
  python3 db/harvest_sitemap.py --source yamaha --dry-run
  python3 db/harvest_sitemap.py --source yamaha --ingest
  python3 db/harvest_sitemap.py --all --ingest
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
CACHE = Path(__file__).resolve().parent / "cache"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")

# Szín- és kivitelváltozatok, amik ugyanazt a modellt jelentik.
COLOUR = {"BK", "WE", "RD", "BN", "GB", "MB", "CB", "BP", "HM"}

SOURCES = {
    # ------------------------------------------------------------------ Yamaha
    "yamaha": {
        "manufacturer": "Yamaha",
        "sitemap": "https://hu.yamaha.com/sitemap.xml",
        # /musical-instruments/<csoport>/products/<alkategoria>/<modell>/
        "pattern": r"/musical-instruments/([^/]+)/products/([^/]+)/([^/]+)/?$",
        # CSAK ezek jonnek be. Ami nincs itt, az kiesik a hangkeltes-teszten:
        # fuvos, vonos, akusztikus uto, gitar, tartozek, allvany, app.
        "allow": {
            "keyboards/synthesizers":            "Keyboard - Synthesizer",
            "keyboards/arranger-workstations":   "Keyboard - Arranger",
            "keyboards/stagekeyboards":          "Keyboard - Piano",
            "keyboards/portable-keyboards":      None,   # PSR-E: kiseroautomatikas, de nem mind
            "keyboards/region-specific-keyboards": None,
            "keyboards/other-keyboard-instruments": None,
            "pianos/clavinova":                  "Keyboard - Piano",
            "pianos/arius":                      "Keyboard - Piano",
            "pianos/p-series":                   "Keyboard - Piano",
            "pianos/portable-grand":             "Keyboard - Piano",
            "pianos/modus":                      "Keyboard - Piano",
            "pianos/avantgrand":                 "Keyboard - Piano",
            "drums/electronic-drum-kits":        "Electronic Drum",
            "drums/electronic-drum-pads":        "Electronic Drum",
            "drums/digital-percussion":          "Electronic Drum",
            "drums/finger-drum-pads":            "Electronic Drum",
            "drums/electronic-trigger-modules":  None,   # hangmodul, nincs meg ra kategoria
            "brass-woodwinds/digital-wind-instruments": None,
        },
        # A sitemap a specs.html / support.html aloldalakat is felsorolja.
        "skip_slug": re.compile(r"\.html?$|^(specs|support|downloads|manuals)$", re.I),
    },
    # ------------------------------------------------------------------- Casio
    "casio": {
        "manufacturer": "Casio",
        "sitemap": "https://www.casio.com/europe/sitemap.xml",
        # .../electronic-musical-instruments/<szekcio>/product.<KOD>/
        "pattern": r"/electronic-musical-instruments/(?:([^/]+)/)?product\.([^/]+)/?$",
        "allow": None,          # itt maga az utvonal szurjon: lasd casio_filter
        "skip_section": {"options"},   # adapter, allvany, pedal, taska
        "skip_slug": re.compile(r"^$"),
    },
}


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sSL", "--max-time", "60", "--compressed", "-A", UA,
                    url, "-o", str(dest)], check=True)
    return dest


def sitemap_locs(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.findall(r"<loc>([^<]+)</loc>", text)


def tidy_model(slug):
    """'psr-e443' -> 'PSR-E443', 'stage-custom-birch' -> 'Stage Custom Birch'."""
    slug = urllib.parse.unquote(slug).strip("/")
    if re.fullmatch(r"[a-z]{1,6}[-]?[a-z]?\d[\w.-]*", slug, re.I) or re.search(r"\d", slug):
        return slug.upper() if len(slug) <= 18 else slug.upper()
    return " ".join(w.capitalize() for w in slug.split("-"))


def collapse_variant(name):
    """PX-S1100BK es PX-S1100WE ugyanaz a modell."""
    n = name.upper()
    if n.endswith("SET"):
        n = n[:-3]
    if len(n) > 2 and n[-2:] in COLOUR:
        n = n[:-2]
    return n


def harvest(key, refresh):
    src = SOURCES[key]
    cache = CACHE / f"sitemap-{key}.xml"
    if refresh or not cache.exists():
        fetch(src["sitemap"], cache)
    pat = re.compile(src["pattern"])

    found = {}          # modellnev -> (url, kategoria)
    skipped = 0
    for url in sitemap_locs(cache):
        m = pat.search(url.rstrip("/") + "/")
        if not m:
            continue
        groups = m.groups()
        if key == "casio":
            section, slug = groups[0] or "", groups[1]
            if section in src["skip_section"]:
                skipped += 1
                continue
            name, category = collapse_variant(slug), None
        else:
            group, sub, slug = groups
            path = f"{group}/{sub}"
            if path not in src["allow"]:
                skipped += 1
                continue
            if src["skip_slug"].search(slug):
                continue
            name, category = tidy_model(slug), src["allow"][path]
        if not name or name in found:
            continue
        found[name] = (url, category)
    return found, skipped


def ingest(key, found, dry):
    src = SOURCES[key]
    con = sqlite3.connect(DB)
    row = con.execute("SELECT id FROM manufacturers WHERE canonical_name=?",
                      (src["manufacturer"],)).fetchone()
    if not row:
        sys.exit(f"nincs ilyen gyarto: {src['manufacturer']}")
    mid = row[0]
    have = {re.sub(r"[^a-z0-9]", "", r[0].lower())
            for r in con.execute("SELECT name FROM instruments WHERE manufacturer_id=?", (mid,))}
    ts = now_iso()
    new, catted = [], 0
    for name, (url, category) in sorted(found.items()):
        if re.sub(r"[^a-z0-9]", "", name.lower()) in have:
            continue
        new.append((name, category))
        if category:
            catted += 1      # a proba is szamolja, kulonben nullat jelent
        if dry:
            continue
        con.execute("""INSERT INTO instruments (manufacturer_id, name, year, category,
                       source_url, created_at) VALUES (?,?,NULL,?,?,?)""",
                    (mid, name, category, url, ts))
        iid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        if category:
            con.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
            cid = con.execute("SELECT id FROM categories WHERE name=?", (category,)).fetchone()[0]
            con.execute("""INSERT OR IGNORE INTO instrument_categories
                           (instrument_id, category_id, is_primary) VALUES (?,?,1)""", (iid, cid))
    if not dry:
        con.execute("""UPDATE source_domains SET harvester='harvest_sitemap'
                       WHERE domain=? """, (urllib.parse.urlparse(src["sitemap"]).netloc,))
        con.commit()
    return new, catted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    if args.list:
        for k, s in sorted(SOURCES.items()):
            allow = "minden termek" if s["allow"] is None else f"{len(s['allow'])} alkategoria"
            print(f"  {k:8} {s['manufacturer']:10} {allow:20} {s['sitemap']}")
        return

    keys = sorted(SOURCES) if args.all else ([args.source] if args.source else [])
    if not keys:
        ap.print_help()
        return

    for key in keys:
        found, skipped = harvest(key, args.refresh)
        new, catted = ingest(key, found, dry=not args.ingest)
        print(f"{key}: {len(found)} modell a sitemapbol, {skipped} kihagyva scope miatt, "
              f"{len(new)} uj, ebbol {catted} kategoriaval")
        for name, cat in new[:12]:
            print(f"    {name:22} {cat or ''}")
        if len(new) > 12:
            print(f"    ... es meg {len(new) - 12}")
        if not args.ingest:
            print("  -- proba, semmi nem irodott; --ingest ir --")


if __name__ == "__main__":
    main()
