#!/usr/bin/env python3
"""synth-db.com oldalainak letoltese cache-be. INGYENES lepes, nulla modell.

Kristof, 2026-09-02: "Ok, ez a letolto mehet."

MIERT KULON LEPES
=================
Az evszam es a kategoria csak az oldalak szoveges leirasaban van meg, azt
modellnek kell kiolvasnia (processing_backlog: synthdb_page_readout, kb. 1,65
millio token). Az a lepes dragabb, es ha halozat kozben szakad meg, karba vesz.

Ezert eloszor CSAK letoltunk. A letoltes halozat, nem modell, tehat nem kerul
semmibe. Ha megvan, a dragabb resz kesobb halozat nelkul, adagokban,
ujraprobalhatoan futhat ugyanarrol a lemezrol.

MIT CSINAL
==========
Vegigmegy a sitemap /synths/ cimein, letolti oket, kiszedi a HTML-bol a
szoveget, es fajlonkent elteszi a db/cache/synthdb/ ala. Ami mar megvan, azt
kihagyja, tehat barmikor ujrainditható es folytatja ott, ahol abbahagyta.

UDVARIASSAG: 1,2 masodperc szunet a keresek kozott. Ez egy kis oldal, nem
verjuk szet. 1903 oldal igy nagyjabol 40 perc.

A LETOLTOTT SZOVEG ADAT, NEM UTASITAS. Aki kesobb modellnek adja, annak ezt a
promptjaban ki kell mondania.

Hasznalat:
    python3 db/cache_synthdb_pages.py            # folytatja amit lehet
    python3 db/cache_synthdb_pages.py --limit 50 # csak 50 oldal (proba)
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache" / "synthdb"
SITEMAP = "http://www.synth-db.com/sitemap.xml"   # HTTPS NINCS
UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")
DELAY = 1.2


def slug(mfr, model):
    base = re.sub(r"[^A-Za-z0-9]+", "-", f"{mfr}--{model}").strip("-")[:120]
    return f"{base}-{hashlib.sha1(f'{mfr}/{model}'.encode()).hexdigest()[:8]}.json"


def to_text(html):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    h = re.sub(r"(?is)<!--.*?-->", " ", h)
    t = re.sub(r"(?s)<[^>]+>", "\n", h)
    t = re.sub(r"[ \t]+", " ", t)
    t = "\n".join(line.strip() for line in t.split("\n") if line.strip())
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="csak ennyi UJ oldalt toltson le")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sSL", "--max-time", "60", "-A", UA, SITEMAP],
                       capture_output=True, text=True)
    urls = [u for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.stdout) if "/synths/" in u]
    print(f"{len(urls)} oldal a sitemapban")

    done = skipped = failed = 0
    for i, url in enumerate(urls, 1):
        parts = urllib.parse.unquote(url.split("/synths/", 1)[1]).split("/")
        if len(parts) < 2:
            continue
        mfr, model = parts[0].strip(), parts[1].strip()
        path = CACHE / slug(mfr, model)
        if path.exists():
            skipped += 1
            continue
        if args.limit and done >= args.limit:
            break
        enc = urllib.parse.quote(url, safe=":/")
        # BYTE-ban kerjuk, NEM text=True-val. Az oldal nem UTF-8: 2026-09-02-en
        # a letoltes 23 oldal utan elszallt egy 0x92-es bajton (Windows-1252
        # gorbe aposztrof), es a text=True miatt maga a subprocess dobta el,
        # tehat nem lehetett elkapni oldal-szinten. Byte-ban jon, mi dontjuk el
        # hogyan olvassuk: eloszor utf-8, aztan cp1252, vegul csere.
        g = subprocess.run(["curl", "-sSL", "--max-time", "30", "-A", UA, enc],
                           capture_output=True)
        time.sleep(DELAY)
        if g.returncode != 0 or not g.stdout:
            failed += 1
            print(f"  ! nem jott le: {mfr} / {model}")
            continue
        raw = g.stdout
        for codec in ("utf-8", "cp1252"):
            try:
                page = raw.decode(codec)
                break
            except UnicodeDecodeError:
                continue
        else:
            page = raw.decode("utf-8", errors="replace")
        path.write_text(json.dumps({
            "manufacturer": mfr, "model": model, "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "text": to_text(page),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        if done % 50 == 0:
            print(f"  {done} letoltve, {i}/{len(urls)} vegignezve")

    print(f"\nletoltve: {done}   mar megvolt: {skipped}   nem sikerult: {failed}")
    print(f"cache: {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
