#!/usr/bin/env python3
"""Meri, hogy egy 'harvestable' domain sitemapjabol tenyleg jon-e TERMEK.

MIERT KELL. A source_domains.verdict='harvestable' eddig azt jelentette, hogy a
domain kiad egy sitemapot, es a sitemap_urls oszlopba az OSSZES URL szama
kerult. Ez proxy, nem eredmeny. A behringer.com peldaul 84 URL-lel 'harvestable',
de a 84 kozott EGYETLEN termekoldal sincs, csak nyelvi fooldalak es egy
/products gyujto. Ha a 92-es szamot ugy hasznaljuk, mint "92 forras, amibol
adat jon", akkor tulbecsuljuk magunkat.

Ez a szkript a KIMENETET meri, nem a proxyt: koveti a sitemapindexet, es
megszamolja, hany URL nez ki TERMEKOLDALNAK. A verdictet NEM irja at (az a
robots/elerhetoseg kerdese, es az valtozatlanul igaz) -- uj oszlopokba ir:
product_urls (meglevo) es a note-ba egy meres-cimke.

Udvarias: soronkent egy keres, 1 masodperc szunet, max 12 al-sitemap
domainenkent, 5 MB felett nem olvas tovabb.

Hasznalat:
  python3 db/probe_sitemap_yield.py --list          # mit merne
  python3 db/probe_sitemap_yield.py --limit 10      # szarazproba, nem ir DB-t
  python3 db/probe_sitemap_yield.py --all --write   # meres + DB-be iras
"""
import re
import sys
import time
import sqlite3
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = "Mozilla/5.0 (compatible; SynthsworldBot/1.0; +kutatas, nem kereskedelmi)"
MAX_SUB_SITEMAPS = 12
MAX_BYTES = 5_000_000
PAUSE = 1.0

LOC_RX = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)

# Egy URL akkor "termekszeru", ha az utvonalaban ott van a termek-jelzo ES
# marad utana egy sajat slug. A /en/products (gyujto) igy NEM szamit bele,
# a /product/prophet-12-keyboard/ viszont igen.
PRODUCT_RX = re.compile(
    r"/(?:product|products|produkt|produkte|termek|instrument|instruments|"
    r"gear|synth|synthesizers?|keyboards?)/(?P<slug>[^/?#]+)/?$", re.I)

# Ami slugnak latszik, de nem termek.
SLUG_BLOCKLIST = re.compile(
    r"^(index|all|list|archive|category|categories|page|\d{1,2})$|\.(html?|php|xml)$", re.I)


def fetch(url, timeout=25):
    try:
        r = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(timeout),
             "--max-filesize", str(MAX_BYTES), "-A", UA, url],
            capture_output=True, timeout=timeout + 10)
        return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def collect_urls(entry_url):
    """Osszes URL a sitemapbol, a sitemapindexet egy szinttel kovetve.
    Visszaad: (urlok, hany al-sitemapot olvastunk, elertuk-e a plafont)"""
    text = fetch(entry_url)
    if not text:
        return [], 0, False
    locs = LOC_RX.findall(text)
    if "<sitemapindex" not in text.lower():
        return locs, 0, False

    subs = [u for u in locs if u.lower().endswith((".xml", ".xml.gz"))]
    capped = len(subs) > MAX_SUB_SITEMAPS
    urls = []
    for sub in subs[:MAX_SUB_SITEMAPS]:
        time.sleep(PAUSE)
        body = fetch(sub)
        if body:
            urls.extend(LOC_RX.findall(body))
    return urls, min(len(subs), MAX_SUB_SITEMAPS), capped


def product_like(urls):
    out = []
    for u in urls:
        m = PRODUCT_RX.search(u)
        if not m:
            continue
        slug = m.group("slug")
        if SLUG_BLOCKLIST.search(slug):
            continue
        out.append(u)
    return out


def validate(con):
    """Futtasd a detektort azon, amirol MAR TUDJUK a valaszt.

    MIERT LETEZIK EZ. 2026-09-04-en ez a szkript "21 ad termeket, 67 nem"
    eredmenyt adott, es Kristof EGYETLEN linkkel dontotte meg
    (https://www.synthxl.com/waldorf-pulse/). A detektor az URL ALAKJARA nezett,
    /product/-szeru utszakaszt keresett, es a lapos cimeket (synthxl.com/
    waldorf-pulse/) nem ismerte fel. Nyolc olyan domainre irt nullat, ahonnan
    egyutt 1387 hangszer szarmazik.

    A hiba nem az volt, hogy a regex tokeletlen: az mindig az lesz. A hiba az
    volt, hogy a szamot ELOBB adtam tovabb, mint hogy lefuttattam volna azon,
    amirol mar volt igazsagunk. Ez a fuggveny az a lepes, ami akkor kimaradt,
    es ezert NEM opcionalis: a --all futas magatol lefuttatja, es ha bukik,
    kiirja, hogy az eredmenynek nem szabad dontesi alapkent hasznalni.

    A merce: minden domain, amirol MAR van hangszerunk. Ha a detektor ezekre
    nullat mond, akkor az ismeretlen domainekrol sem mond igazat."""
    rows = con.execute("""
        SELECT sd.domain, COALESCE(sd.product_urls, -1),
               (SELECT COUNT(*) FROM instruments i WHERE i.source_url LIKE '%'||sd.domain||'%')
        FROM source_domains sd
        WHERE sd.verdict='harvestable' AND sd.route='sitemap'
    """).fetchall()
    known = [r for r in rows if r[2] > 0]
    failed = [r for r in known if r[1] == 0]
    print("--- VALIDACIO: a detektor a mar bizonyitott forrasokon ---")
    if not known:
        print("nincs meg mert bizonyitott forras, a validacio nem eldontheto")
        return None
    for d, pu, inst in sorted(failed, key=lambda r: -r[2]):
        print(f"  BUKTA  {d:28} mert termek=0, pedig {inst} hangszerunk van innen")
    lost = sum(r[2] for r in failed)
    print(f"  {len(known) - len(failed)}/{len(known)} bizonyitott forrason helyes; "
          f"{len(failed)} bukott, osszesen {lost} hangszernyi bizonyitek ellenere")
    return not failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="csak a validacio a mar bizonyitott forrasokon, meres nelkul")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--write", action="store_true", help="eredmeny DB-be irasa")
    args = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    if args.validate:
        ok = validate(con)
        con.close()
        return 0 if ok else 1
    rows = con.execute("""
        SELECT domain, route_url, COALESCE(sitemap_urls, 0), COALESCE(inbound_links, 0)
        FROM source_domains
        WHERE verdict='harvestable' AND route='sitemap' AND route_url IS NOT NULL
        ORDER BY inbound_links DESC, sitemap_urls DESC
    """).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    if args.list:
        for d, u, n, inb in rows:
            print(f"{inb:5} link  {n:6} url  {d:32} {u}")
        print(f"\nosszesen {len(rows)} domain")
        return 0

    print(f"{'domain':32} {'osszes':>7} {'termek':>7}  megjegyzes")
    total_with, total_without = 0, 0
    for i, (domain, url, _n, _inb) in enumerate(rows, 1):
        urls, subs, capped = collect_urls(url)
        prods = product_like(urls)
        note = ""
        if not urls:
            note = "nem jott sitemap"
        elif not prods:
            note = "NINCS termekoldal a sitemapban"
        if capped:
            note += f" (csak {MAX_SUB_SITEMAPS} al-sitemap olvasva)"
        print(f"{domain:32} {len(urls):7} {len(prods):7}  {note}")
        sys.stdout.flush()

        if prods:
            total_with += 1
        else:
            total_without += 1

        if args.write:
            con.execute(
                "UPDATE source_domains SET product_urls=?, sitemap_urls=?,"
                " harvester=COALESCE(harvester, NULL), last_checked=?,"
                " note=COALESCE(note,'') || ? WHERE domain=?",
                (len(prods), len(urls),
                 datetime.now(timezone.utc).isoformat(),
                 f" [sitemap-hozam merve {datetime.now(timezone.utc).date()}: "
                 f"{len(prods)}/{len(urls)}]",
                 domain))
            con.commit()
        time.sleep(PAUSE)

    print()
    print(f"termekoldalt AD:     {total_with}")
    print(f"termekoldalt NEM ad: {total_without}")
    print()
    ok = validate(con)
    if ok is False:
        print()
        print("FIGYELEM: a detektor elbukott olyan forrasokon, amelyekrol mar")
        print("bizonyitottan van adatunk. A fenti ket szamot NE add tovabb")
        print("dontesi alapkent, es ne irj belole Telegram-uzenetet. Eloszor a")
        print("detektort kell megjavitani, aztan ujra merni.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
