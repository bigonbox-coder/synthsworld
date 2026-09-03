#!/usr/bin/env python3
"""MATRIXSYNTH poszt-kereso: megerositi a modellnevet es linket ad hozza.

Kristof, 2026-09-03: "ezt megcsinalhatod a leszedot m.matrixsynth.com".

MIT AD EZ A FORRAS, ES MIT NEM
==============================
A matrixsynth egy Blogger-blog, 262 ezer poszttal, es MARKANEVEKKEL CIMKEZ.
Nem enciklopedia: nem mond evszamot, nem mond cegtortenetet. Amit ad, az ket
dolog, es mindketto pont az, ami ma hianyzik:

  1. MEGEROSITES. Ha egy modellnevre van poszt, ami a gyartot is emliti, akkor
     az a modell letezik. A sequencer.de-rol 247 modellnev all nyomkent, mert
     az a lista maga semmit nem igazol, es az oldalt nem tudjuk megnyitni.
  2. HIVATKOZAS. A poszt URL-je odakerul a hangszerhez kulso linkkent.

NEM SCRAPELES: a Blogger sajat JSON-feedjet kerdezzuk
(/feeds/posts/summary?alt=json&q=...), ugyanazt, amit a blog sajat kereseje.
A robots.txt ures, nincs tiltas. Ket masodperc szunet a keresek kozott, es
minden valasz a cache-be kerul, tehat egy ujrafutas nem terheli megint.

A TALALAT NEM ELEG, MEG KELL NEZNI
==================================
A Blogger keresese LAZA: a "Doncamatic" keresesre harom Korg-posztot ad
vissza, amikbol egyik sem emliti a Doncamaticot. Ezert minden talalatot
ellenorzunk: a modellnev normalizalt alakja SZO SZERINT szerepeljen a poszt
cimeben vagy kivonataban, ES a gyarto neve is jelenjen meg a cimben, a
kivonatban vagy a cimkek kozott. Ami ezen nem megy at, az nem talalat.

Hasznalat:
  python3 db/harvest_matrixsynth.py --limit 60            # szarazfutas, meres
  python3 db/harvest_matrixsynth.py --limit 400 --ingest  # linkek beirasa
  python3 db/harvest_matrixsynth.py --leads --limit 120   # a nyomlista ellenorzese
"""

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "matrixsynth"
FEED = "https://www.matrixsynth.com/feeds/posts/summary"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
PAUSE = 2.0
SOURCE = "matrixsynth"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch(query):
    """Egy kereses, cache-elve. -> a feed entry-listaja."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    path = CACHE / f"q-{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), True
    url = f"{FEED}?alt=json&max-results=10&q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    entries = []
    for e in data.get("feed", {}).get("entry", []) or []:
        entries.append({
            "title": e.get("title", {}).get("$t", ""),
            "summary": re.sub(r"<[^>]+>", " ", e.get("summary", {}).get("$t", "")),
            "labels": [c.get("term", "") for c in e.get("category", []) or []],
            "url": next((l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"), ""),
            "published": e.get("published", {}).get("$t", ""),
        })
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    time.sleep(PAUSE)
    return entries, False


def verify(entries, model, maker):
    """A laza keresest szigoruan atszurjuk. -> a megfelelo posztok."""
    nm, nk = norm(model), norm(maker)
    if len(nm) < 3:          # tul rovid nev, barmire illene
        return []
    out = []
    for e in entries:
        hay = norm(e["title"] + " " + e["summary"])
        if nm not in hay:
            continue
        if nk and nk not in hay and not any(nk in norm(l) for l in e["labels"]):
            continue
        out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--leads", action="store_true",
                    help="a sequencer.de nyomlistajat ellenorzi, nem a sajat hangszereinket")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Sorrend: eloszor azok a hangszerek, amiknek NINCS forrasuk vagy jelolve
    # vannak. Ott a legnagyobb a hozam, mert eppen az hianyzik, amit ez ad.
    rows = conn.execute(
        """SELECT i.id, i.name, i.year, m.canonical_name AS maker
           FROM instruments i JOIN manufacturers m ON m.id = i.manufacturer_id
           WHERE NOT EXISTS (SELECT 1 FROM external_links l
                             WHERE l.instrument_id = i.id AND l.source_name = ?)
           ORDER BY (i.review_status = 'needs_review') DESC,
                    (i.source_url IS NULL) DESC,
                    i.id
           LIMIT ?""", (SOURCE, args.limit)).fetchall()

    checked = hits = added = cached = 0
    for r in rows:
        try:
            entries, from_cache = fetch(f"{r['maker']} {r['name']}")
        except Exception as exc:                      # halozat, 4xx, barmi
            print(f"  HIBA {r['maker']} {r['name']}: {exc}")
            continue
        checked += 1
        cached += from_cache
        good = verify(entries, r["name"], r["maker"])
        if not good:
            continue
        hits += 1
        best = good[0]
        print(f"  {r['maker']} {r['name']}: {best['title'][:70]}")
        if args.ingest:
            exists = conn.execute(
                "SELECT 1 FROM external_links WHERE instrument_id = ? AND url = ?",
                (r["id"], best["url"])).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO external_links
                       (manufacturer_id, instrument_id, url, domain, label, link_type,
                        found_on, source_name, status)
                       VALUES ((SELECT manufacturer_id FROM instruments WHERE id = ?),
                               ?, ?, 'matrixsynth.com', ?, 'community', ?, ?, 'unchecked')""",
                    (r["id"], r["id"], best["url"], best["title"][:200], FEED, SOURCE))
                added += 1

    if args.ingest:
        conn.commit()
    print(f"\nellenorizve: {checked} hangszer ({cached} a cache-bol), "
          f"megerositve: {hits}, uj link: {added}")
    if checked:
        print(f"talalati arany: {hits / checked:.0%}")
    print("" if args.ingest else "-- szarazfutas, --ingest kell hozza --")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
