#!/usr/bin/env python3
"""Megméri, hogy egy forrás-domain géppel feldolgozható-e.

Kristóf kérdése volt: honnan tudja a script, melyik oldalon lesznek a
legrelevánsabb találatok, a legkönnyebb feldolgozhatóság mellett. A válasz az,
hogy ezt nem kell kitalálni, mert MÉRHETŐ. Három dolgot nézünk meg minden
jelöltnél, ebben a sorrendben:

  1. robots.txt -- szabad-e egyáltalán. Ha kifejezetten tiltja, MEGÁLLUNK.
  2. van-e sitemap. Ez a döntő: sitemappal a HTML botvédelme lényegtelen.
  3. hány cím néz ki benne termékoldalnak. Ez a hozam.

A Casio és a Yamaha pont ezen a három lépésen ment át ma este: mindkettő
tiltja a HTML-t, és mindkettő kiadja a sitemapot háromezer termékoldallal.

A "nem megy" nem egyetlen dolog, ezért a verdict mellé mindig OK kerül. Egy
tiltólista csak annyit mondana, hogy nem megy, és attól jövő héten ugyanúgy
nekifutnánk. A `blocked_policy` az egyetlen végleges: azt tiszteletben tartjuk.

Használat:
  python3 db/probe_domains.py --top 20        # a legigéretesebb, még nem mért domainek
  python3 db/probe_domains.py --domain yamaha.com
  python3 db/probe_domains.py --report        # mi az állás
"""

import argparse
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")

# Amit egy termékoldal címe tartalmazni szokott. Szándékosan tág: a cél a
# nagyságrend, nem a pontos szám.
PRODUCT_HINT = re.compile(
    r"/(product|products|produkt|instrument|instruments|gear|synth|synthesizer|"
    r"keyboard|keyboards|piano|drum|drums|sampler|module|models?)[/.]", re.I)

# Ezeket kézzel jegyezzük be, mert nem méréssel derülnek ki. A ModularGrid a
# fontos eset: kifejezetten tiltja az AI-crawlereket, tehát megállunk.
KNOWN = {
    "modulargrid.net": ("blocked_policy",
                        "robots.txt tiltja az AI-crawlereket, a tartalom ráadásul JS-bol renderelodik",
                        "Jogtiszta ut: engedelykeres, vagy a felhasznaloi modul-adatlapok helyett a gyartoi oldalak."),
    "encyclotronic.com": ("gone",
                          "a domain ma a JackHertz.com-ra iranyit at, az adatbazis nincs mogotte",
                          "Wayback-fedettseg 2026-09-01-en nem volt megallapithato: a CDX 403-at ad nekunk."),
    "web.archive.org": ("blocked_bot",
                        "a CDX kereso 403-at ad, az availability vegpont ures listat -- blokkolas mellett nem hiheto",
                        "Ujraprobalando mas utvonalrol vagy kesobb."),
    "electronicmusic.fandom.com": ("harvestable",
                                   "a HTML 402/403, DE az api.php?action=parse&prop=wikitext nyitva",
                                   "Minden fandom wikin ugyanez a trukk."),
}


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def get(url, timeout=25):
    """-> (http_code, text). Halkan bukik, mert a bukas is adat."""
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "--compressed", "-A", UA,
         "-w", "\n%{http_code}", url],
        capture_output=True, text=True, errors="replace")
    out = r.stdout or ""
    code = out.rsplit("\n", 1)[-1].strip() if "\n" in out else "0"
    body = out.rsplit("\n", 1)[0] if "\n" in out else ""
    if not code.isdigit():
        code = "0"
    return int(code), body, (r.stderr or "").strip()


def probe(domain):
    """-> dict a source_domains oszlopaihoz."""
    if domain in KNOWN:
        v, reason, note = KNOWN[domain]
        return {"verdict": v, "reason": reason, "note": note}

    base = f"https://{domain}"
    res = {"robots_ok": None, "sitemap_urls": None, "product_urls": None,
           "route": None, "route_url": None}

    # 1. robots
    code, body, err = get(base + "/robots.txt", 15)
    sitemaps = []
    if code == 200:
        res["robots_ok"] = 0 if re.search(r"(?im)^\s*User-agent:\s*\*\s*$(?:\n(?!\s*User-agent).*)*?^\s*Disallow:\s*/\s*$", body) else 1
        sitemaps = re.findall(r"(?im)^\s*Sitemap:\s*(\S+)", body)
    elif code == 0:
        return {**res, "verdict": "transport",
                "reason": f"nem jott letre a kapcsolat: {err[:120] or 'ismeretlen'}"}

    if res["robots_ok"] == 0:
        return {**res, "verdict": "blocked_policy",
                "reason": "a robots.txt mindenkinek tiltja az egesz oldalt"}

    # 2. sitemap
    for cand in sitemaps + [base + "/sitemap.xml", base + "/sitemap_index.xml"]:
        code, body, _ = get(cand, 40)
        if code != 200 or "<loc>" not in body:
            continue
        locs = re.findall(r"<loc>([^<]+)</loc>", body)
        # sitemap-index: nyissuk ki az elsot, hogy legyen fogalmunk a hozamrol
        if "<sitemapindex" in body[:400].lower() and locs:
            code2, body2, _ = get(locs[0], 40)
            if code2 == 200:
                locs = re.findall(r"<loc>([^<]+)</loc>", body2) or locs
        res["sitemap_urls"] = len(locs)
        res["product_urls"] = sum(1 for u in locs if PRODUCT_HINT.search(u))
        res["route"], res["route_url"] = "sitemap", cand
        return {**res, "verdict": "harvestable",
                "reason": f"sitemap {len(locs)} cimmel, ebbol {res['product_urls']} termekoldalnak latszik"}

    # 3. maga a fooldal
    code, body, err = get(base + "/", 25)
    if code == 200:
        return {**res, "verdict": "html_only", "route": "html", "route_url": base + "/",
                "reason": "nincs sitemap, de a HTML elerheto"}
    if code in (401, 402, 403, 429):
        return {**res, "verdict": "blocked_bot",
                "reason": f"a fooldal HTTP {code} -- KERESD az API-t vagy egy masik belepesi pontot"}
    if code in (404, 410):
        return {**res, "verdict": "gone", "reason": f"a fooldal HTTP {code}"}
    return {**res, "verdict": "transport",
            "reason": f"HTTP {code}; {err[:120]}"}


def save(con, domain, r):
    con.execute("INSERT OR IGNORE INTO source_domains (domain) VALUES (?)", (domain,))
    con.execute("""UPDATE source_domains SET verdict=?, reason=?, route=?, route_url=?,
                   robots_ok=?, sitemap_urls=?, product_urls=?,
                   note=COALESCE(?, note), last_checked=? WHERE domain=?""",
                (r["verdict"], r.get("reason"), r.get("route"), r.get("route_url"),
                 r.get("robots_ok"), r.get("sitemap_urls"), r.get("product_urls"),
                 r.get("note"), now_iso(), domain))
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, metavar="N",
                    help="a N legigeretesebb meg nem mert domain megmerese")
    ap.add_argument("--domain", help="egy konkret domain")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(DB)

    if args.report:
        print("itelet szerint:")
        for v, n in con.execute("SELECT verdict, COUNT(*) FROM source_domains GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  {n:5d}  {v}")
        print("\nfeldolgozhato, hozam szerint:")
        for d, p, u, r in con.execute("""SELECT domain, product_urls, sitemap_urls, route_url
                FROM source_domains WHERE verdict='harvestable'
                ORDER BY COALESCE(product_urls,0) DESC LIMIT 15"""):
            print(f"  {str(p or '?'):>6} termekoldal / {str(u or '?'):>6} cim   {d}   {r or ''}")
        print("\namit tudunk hogy jo, de nem szedjuk le:")
        for d, v, why, note in con.execute("""SELECT domain, verdict, reason, note FROM source_domains
                WHERE verdict IN ('blocked_policy','blocked_bot','gone','transport')
                ORDER BY COALESCE(inbound_spread,0) DESC"""):
            print(f"  [{v}] {d}\n      {why or ''}\n      {note or ''}".rstrip())
        return

    if args.domain:
        targets = [args.domain]
    elif args.top:
        targets = [r[0] for r in con.execute("""SELECT domain FROM source_domains
            WHERE verdict='untested' ORDER BY COALESCE(inbound_spread,0) DESC LIMIT ?""", (args.top,))]
    else:
        ap.print_help()
        return

    for i, d in enumerate(targets, 1):
        r = probe(d)
        save(con, d, r)
        print(f"[{i}/{len(targets)}] {d:34} {r['verdict']:15} {r.get('reason','')[:70]}")
        time.sleep(1.5)   # legyunk illendo vendegek


if __name__ == "__main__":
    main()
