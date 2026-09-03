#!/usr/bin/env python3
"""RETRO SYNTH ADS: korabeli hirdetesek, cimkezve evszammal es modellnevvel.

Kristof, 2026-09-03: "ok, mehet". A forras-meres ezt hozta ki a 91 leszedheto
domainbol a legigeretesebbnek, mert EVSZAMOT igerhet, es abbol van a legnagyobb
hianyunk (3135 hangszerbol 1530-nak nincs).

MIERT EPPEN EZ AZ OLDAL
=======================
Blogger-blog, 608 poszttal, es a szerzo VEGIG CIMKEZ: minden poszton ott a
megjelenes eve (nyers negyjegyu cimke), a gyarto neve, es a hirdetett modellek
neve kulon-kulon. Peldaul:
    "Yamaha SY-22 Vector Synthesis advertisement, Keyboard 1990"
    cimkek: 1990, keyboard magazine, sy-22, synthesizer, yamaha
Ez strukturalt adat, nem proza. A Blogger sajat JSON-feedjet kerdezzuk, ket
keresben az egesz blog megvan. A robots.txt csak a /search-ot tiltja, a /feeds
engedett.

AMIT NEM SZABAD: A HIRDETES EVE NEM A MEGJELENES EVE
====================================================
Egy 1990-es SY-22 hirdetes annyit bizonyit, hogy a hangszer 1990-BEN MAR
LETEZETT. Felso becsles, nem datum. Ezert ez a script alapbol NEM ir evszamot
a hangszerhez. Amit ir: a poszt URL-jet kulso linkkent, es a legkorabbi
hirdetes evet JEGYZETKENT.

Hogy a "legkorabbi hirdetes eve" mennyire jo kozelites, az MERHETO, es a
--measure kapcsolo meg is meri: azokon a hangszereken, ahol MAR TUDJUK az
evszamot, osszeveti a kettot. Ha a meres jol jon ki, abbol lehet levezetesi
szabalyt javasolni (db/derive_facts.py --propose), es a bevezetes Kristof
dontese.

Hasznalat:
  python3 db/harvest_retrosynthads.py --fetch      # feed letoltese a cache-be
  python3 db/harvest_retrosynthads.py --measure    # a hirdetes-ev vs ismert ev
  python3 db/harvest_retrosynthads.py --ingest     # linkek es jegyzetek
"""

import argparse
import json
import re
import sqlite3
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "retrosynthads"
FEED = "https://retrosynthads.blogspot.com/feeds/posts/summary"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
SOURCE = "retrosynthads"
YEAR = re.compile(r"^(19[4-9]\d|20[0-2]\d)$")

# Cimkek, amik nem gyartok es nem modellek: magazinok, formatumok, temak.
STOP = {
    "artwork", "brochure", "advertisement", "catalog", "catalogue", "flyer",
    "poster", "price list", "retail price list", "manual", "magazine",
    "keyboard magazine", "keyboards computers & software magazine",
    "electronic musician", "music technology", "international musician",
    "sound on sound", "future music", "one two testing", "polyphony",
    "contemporary keyboard", "synthesizer", "synthesizers", "drum machine",
    "drum machines", "sampler", "samplers", "sequencer", "midi sequencer",
    "software", "keyboards", "keyboard", "midi", "modular", "vintage",
    "analog", "analogue", "digital", "we design the future", "effects",
    "guitar", "guitars", "bass", "amplifier", "amplifiers", "mixer", "mixers",
    "monitor", "monitors", "microphone", "recording", "studio",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch_all():
    """A teljes blog ket-harom keresben. -> a posztok listaja."""
    CACHE.mkdir(parents=True, exist_ok=True)
    # A Blogger a max-results-ot sajat maga vagja vissza (500-at kerve 150-et
    # ad), ezert 150-esevel lapozunk, es addig megyunk, amig ures lapot nem kapunk.
    # Az elso valtozat 500-zal kert es a len(page) < 500 feltetelre allt le,
    # ezert a 608 posztbol csak az elso 150 jott meg, es a meres is azon futott.
    PAGE = 150
    posts, start = [], 1
    while True:
        path = CACHE / f"page-{start}.json"
        if path.exists():
            page = json.loads(path.read_text(encoding="utf-8"))
        else:
            url = f"{FEED}?alt=json&max-results={PAGE}&start-index={start}"
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            page = []
            for e in data.get("feed", {}).get("entry", []) or []:
                page.append({
                    "title": e.get("title", {}).get("$t", ""),
                    "labels": [c.get("term", "") for c in e.get("category", []) or []],
                    "url": next((l["href"] for l in e.get("link", [])
                                 if l.get("rel") == "alternate"), ""),
                })
            path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            time.sleep(2.0)
        posts.extend(page)
        if not page:
            break
        start += len(page)
    return posts


def match(posts, conn):
    """Poszt -> (hangszer id, ev, url). Csak ott, ahol a gyarto ES a modell is stimmel."""
    makers = {}
    for mid, name in conn.execute("SELECT id, canonical_name FROM manufacturers"):
        makers[norm(name)] = mid
    for name, mid in conn.execute(
            "SELECT name, manufacturer_id FROM manufacturer_name_history"):
        makers.setdefault(norm(name), mid)
    instruments = defaultdict(dict)
    for iid, mid, iname, iyear in conn.execute(
            "SELECT id, manufacturer_id, name, year FROM instruments"):
        instruments[mid][norm(iname)] = (iid, iname, iyear)

    out = []
    for p in posts:
        labels = [l for l in p["labels"] if l.lower() not in STOP]
        years = sorted(int(l) for l in labels if YEAR.match(l))
        mids = {makers[norm(l)] for l in labels if norm(l) in makers}
        if len(mids) != 1:              # nulla vagy tobb gyarto: nem dontunk
            continue
        mid = mids.pop()
        # KERESZTHIVATKOZAS-SZURO. A blog szerzoje egy 1983-as Roland-brosurat
        # egyszerre cimkezett tb-303-mal ES TB-3-mal, tr-808-cal ES TR-8-cal,
        # vagyis a MAI Aira-nevekkel is, utalaskent. Igy a 2014-es TB-3-unk egy
        # 1983-as hirdetesre illeszkedett. Szabaly: ha egy cimke SZIGORU
        # ELOTAGJA egy masik cimkenek ugyanazon a poszton, es a folytatas
        # szamjegy, akkor az a rovid cimke utalas, nem a poszt targya.
        keys = [norm(l) for l in labels]
        crossref = {k for k in keys if k and any(
            o != k and o.startswith(k) and o[len(k):].isdigit() for o in keys)}

        for l in labels:
            if YEAR.match(l) or norm(l) in makers or norm(l) in crossref:
                continue
            hit = instruments[mid].get(norm(l))
            if hit:
                out.append({"iid": hit[0], "name": hit[1], "known_year": hit[2],
                            "ad_year": years[0] if years else None,
                            "url": p["url"], "title": p["title"], "mid": mid})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    args = ap.parse_args()

    posts = fetch_all()
    print(f"poszt: {len(posts)}")
    conn = sqlite3.connect(DB)
    hits = match(posts, conn)
    by_inst = defaultdict(list)
    for h in hits:
        by_inst[h["iid"]].append(h)
    print(f"parositott poszt: {len(hits)}, kulonbozo hangszer: {len(by_inst)}")

    if args.measure:
        # A LENYEG: a legkorabbi hirdetes eve mennyire kozelit a MAR ISMERT
        # evszamhoz. Ha ez jol jon ki, levezetesi szabalyt lehet belole javasolni.
        diffs = Counter()
        for iid, rows in by_inst.items():
            known = rows[0]["known_year"]
            ads = [r["ad_year"] for r in rows if r["ad_year"]]
            if not known or not ads:
                continue
            diffs[min(ads) - known] += 1
        total = sum(diffs.values())
        print(f"\nMERES: {total} olyan hangszer, ahol az evszam MAR ismert es van hirdetes")
        for d in sorted(diffs):
            print(f"  legkorabbi hirdetes {d:+d} ev a rogzitett evszamhoz kepest: {diffs[d]}")
        if total:
            ok = sum(v for d, v in diffs.items() if 0 <= d <= 1)
            print(f"  azonos evben vagy egy evvel kesobb: {ok}/{total} = {ok/total:.0%}")
        missing = [i for i, r in by_inst.items()
                   if not r[0]["known_year"] and any(x["ad_year"] for x in r)]
        print(f"  evszam nelkuli hangszer, amire VAN hirdetes-ev: {len(missing)}")

    if args.ingest:
        added = noted = 0
        for iid, rows in by_inst.items():
            best = rows[0]
            for r in rows:
                ex = conn.execute(
                    "SELECT 1 FROM external_links WHERE instrument_id=? AND url=?",
                    (iid, r["url"])).fetchone()
                if ex:
                    continue
                conn.execute(
                    """INSERT INTO external_links
                       (manufacturer_id, instrument_id, url, domain, label, link_type,
                        found_on, source_name, status)
                       VALUES (?, ?, ?, 'retrosynthads.blogspot.com', ?, 'archive', ?, ?, 'unchecked')""",
                    (r["mid"], iid, r["url"], r["title"][:200], FEED, SOURCE))
                added += 1
            ads = [r["ad_year"] for r in rows if r["ad_year"]]
            if ads and not best["known_year"]:
                note = (f"[retrosynthads {time.strftime('%Y-%m-%d')}] Evszam NINCS rogzitve, de "
                        f"a legkorabbi ismert hirdetes {min(ads)}-bol valo, tehat a hangszer "
                        f"ekkor MAR letezett. Ez felso becsles, nem megjelenesi datum, ezert a "
                        f"year mezobe NEM irtam be. {len(rows)} hirdetes-link bekerult.")
                conn.execute(
                    "UPDATE instruments SET review_note = coalesce(review_note,'') || ? WHERE id = ?",
                    (" " + note, iid))
                noted += 1
        conn.commit()
        print(f"\nuj link: {added}, evszam-nyom jegyzetbe: {noted}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
