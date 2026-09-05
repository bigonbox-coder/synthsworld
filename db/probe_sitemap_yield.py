#!/usr/bin/env python3
"""Meri, hogy egy 'harvestable' domain sitemapjabol tenyleg jon-e TERMEK.

MIERT KELL. A source_domains.verdict='harvestable' eddig azt jelentette, hogy a
domain kiad egy sitemapot, es a sitemap_urls oszlopba az OSSZES URL szama
kerult. Ez proxy, nem eredmeny. A behringer.com peldaul 84 URL-lel 'harvestable',
de a 84 kozott EGYETLEN termekoldal sincs, csak nyelvi fooldalak es egy
/products gyujto. Ha a 92-es szamot ugy hasznaljuk, mint "92 forras, amibol
adat jon", akkor tulbecsuljuk magunkat.

=============================================================================
A DETEKTOR TORTENETE -- KET BUKAS, KET TANULSAG. Ne ird ujra ennek ismerete
nelkul, mert mindketto ugyanabba az iranyba huz vissza.

1. BUKAS (2026-09-04 este). Az elso valtozat CSAK az URL ALAKJARA nezett:
   /product/<slug>/ mintat keresett. "21 ad termeket, 67 nem" -- es Kristof
   EGYETLEN linkkel dontotte meg: https://www.synthxl.com/waldorf-pulse/.
   A LAPOS cimeket (nincs /product/ ut, a gyartonev a slug elejen all) nem
   ismerte fel, es nullat irt nyolc olyan domainre, ahonnan egyutt 1637
   hangszerunk szarmazik. TANULSAG: egy termekoldal URL-je otfele alakot vesz
   fel, nem egyet. Lasd a SIGNALS reszt lent.

2. BUKAS (a validacio elso valtozata, ugyanaznap ejjel). A javitas utan a
   validacio meg mindig "bukast" jelzett a muted.io-ra es a solton-acoustic.de-re.
   Megneztem az adatot: a muted.io 57 hangszere MIND UGYANARRA az egy URL-re
   mutat (muted.io/synth-list/), az egy LISTAOLDAL. Ott a detektor helyesen ir
   nullat, es a validacio hazudott, nem a detektor. TANULSAG: ketfele forras
   van, es a sitemap-hozam merese csak az egyikre ertelmes:
     - MODELL-SZINTU forras: minden hangszernek sajat oldala van
       (kulonbozo_url / hangszer ~ 1.0). Ezen a detektornak MUKODNIE KELL.
     - LISTA-FORRAS: sok hangszer egy oldalrol (arany ~ 0). Itt a sitemapban
       nincs termekoldal, es ez IGY HELYES.
   A validacio ezert eloszor OSZTALYOZ, es csak a modell-szintu forrasokon ker
   szamon recallt.

MIT MER A VALIDACIO. Nem azt, hogy a sitemap letezik-e, es nem is azt, hogy a
szam szep-e: fogja azokat az URL-eket, amelyekrol BIZONYITOTTAN tudjuk, hogy
hangszeroldalak (instruments.source_url), es megkerdezi, hogy a detektor
felismeri-e oket. Ez a recall. Kuszob: 0.80 domainenkent. Letoltest nem igenyel,
masodpercek alatt lefut, es barmikor megismetelheto.

MIT NEM MER, es ezt tudni kell rola. A recall nem precizitas. Egy detektor,
ami MINDENT termeknek mond, 100% recallt er el es hasznalhatatlan. Ezert:
  - a meres kiirja a talalati aranyt is (termek / osszes URL). Ha ez 90% folott
    van, az gyanus: minden oldalnak van kategoria-, tag- es infooldala.
  - a `--audit <domain>` letolti nehany olyan URL cimet, amit a detektor
    termeknek mond, de NINCS a bazisunkban, es kiirja oket, hogy latszodjon,
    tenyleg modelloldalak-e. Ez az egyetlen resz, ami halozatot hasznal.
   (Emlek: feedback_measure_the_output_not_just_the_holdout -- a mar ismert
   halmaz a konnyu eseteket tartalmazza es 100%-ot hazudik.)

Udvarias: soronkent egy keres, 1 masodperc szunet, max 12 al-sitemap
domainenkent, 5 MB felett nem olvas tovabb. A letoltott sitemapok a
db/cache/sitemaps/ ala kerulnek, tehat az UJRAMERES INGYEN VAN -- ha a detektor
javul, `--recount` ujraszamol letoltes nelkul.

Hasznalat:
  python3 db/probe_sitemap_yield.py --validate        # csak a detektor vizsgaja
  python3 db/probe_sitemap_yield.py --list
  python3 db/probe_sitemap_yield.py --all --write     # meres + DB-be iras
  python3 db/probe_sitemap_yield.py --recount         # ujraszamlalas a cache-bol
  python3 db/probe_sitemap_yield.py --top 10          # a legjobb jeloltek
  python3 db/probe_sitemap_yield.py --audit synth-db.com
"""
import re
import sys
import time
import json
import sqlite3
import hashlib
import argparse
import subprocess
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
CACHE = Path(__file__).resolve().parent / "cache" / "sitemaps"
UA = "Mozilla/5.0 (compatible; SynthsworldBot/1.0; +kutatas, nem kereskedelmi)"
MAX_SUB_SITEMAPS = 12
MAX_BYTES = 5_000_000
PAUSE = 1.0
RECALL_MIN = 0.80
# Ennyi kulonbozo forras-URL alatt nem mondunk velemenyt a domainrol: 1-2
# hangszer egy hiroldalrol nem bizonyitja, hogy a sitemap tele van modellekkel.
MIN_KNOWN_URLS = 5
# kulonbozo_url / hangszer arany, ami felett modell-szintu forrasnak vesszuk
PER_MODEL_RATIO = 0.5

LOC_RX = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)

# --- SIGNALS ---------------------------------------------------------------
# Ot alak, amiben egy termekoldal cime elofordul. Mindegyik melle odairva a
# MERT pelda, amibol szuletett -- ha valamelyiket kiveszed, tudd, mit vesztesz.
#
#  A  ut-jelzo szegmens, es utana meg van szegmens
#     hu.yamaha.com/en/musical-instruments/keyboards/PRODUCTS/.../cel-53/  (262)
#     synth-db.com/SYNTHS/Ace Tone/FR-70/FR-70.php                        (678)
#     sequential.com/PRODUCT/mopho-x4/                                     (24)
#  B  a gyartonev sajat ut-szegmens, es van utana melyebb szegmens
#     vintagesynth.com/index.php/ARP/odyssey-1                            (364)
#  C  a gyartonev a slug ELEJEN all (lapos cim -- ez bukott el eloszor)
#     synthxl.com/WALDORF-pulse/                                          (249)
#     emumania.net/EMU-orbit-sound-module/                                  (8)
#     synthmania.com/2020/05/13/ALESIS-quadrasynth-plus-piano/             (23)
#  D  a slug "product." elotaggal kezdodik
#     casio.com/europe/electronic-musical-instruments/PRODUCT.AP-270BN/    (39)
MARKERS = {
    "product", "products", "produkt", "produkte", "termek",
    "instrument", "instruments", "gear",
    "synth", "synths", "synthesizer", "synthesizers", "synthesiser", "synthesisers",
    "keyboard", "keyboards", "piano", "pianos", "organ", "organs",
    "drum", "drums", "module", "modules",
}
SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|css|js|xml|gz|zip|mp3|mp4)$", re.I)
# Ezek a szegmensek gyujtooldalt jeleznek. A /blog/ es a /news/ SZANDEKOSAN
# nincs itt: a synthmania minden hangszeroldala datum-uton all, es a C jel
# (gyartonev a slugban) ott a dontő, nem az ut.
SKIP_SEG = {"tag", "tags", "category", "categories", "author", "feed", "comments",
            "search", "wp-content", "wp-json", "cart", "checkout", "account",
            "login", "register", "privacy", "terms"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def maker_keys(con):
    """Gyartonevek normalizalva, a NEVTORTENETTEL egyutt -- a slug allhat a
    regi cegneven (dave-smith-... -> Sequential)."""
    keys = set()
    for (n,) in con.execute("SELECT canonical_name FROM manufacturers"):
        keys.add(norm(n))
    for (n,) in con.execute("SELECT name FROM manufacturer_name_history"):
        keys.add(norm(n))
    return {k for k in keys if len(k) >= 3}


def seg_is_maker(seg, keys):
    """A vintagesynth /akai/ax73 miatt nem eleg a pontos egyezes: az 'akai'
    nalunk 'Akai Professional' neven all, a 'serge' 'Serge Modular' neven, es a
    'teisco-kawai' ket gyartot rak egy szegmensbe. Harom szabaly, ebben a
    sorrendben, mind a 27 vintagesynth-kimaradasra merve."""
    n = norm(seg)
    if n in keys:
        return True
    for part in re.split(r"[-_]+", seg.lower()):          # teisco-kawai, ...-ems
        if len(part) >= 3 and norm(part) in keys:
            return True
    if len(n) >= 5:                                       # akai / akaiprofessional
        for k in keys:
            if len(k) >= 5 and (k.startswith(n) or n.startswith(k)):
                return True
    return False


def slug_maker_head(seg, keys):
    """('waldorf-pulse') -> 'pulse'; ha a slug nem gyartoneven kezdodik: None.
    A gyarto tobb szavas is lehet, ezert a leghosszabb egyezes nyer."""
    parts = [p for p in re.split(r"[-_ ]+", seg.lower()) if p]
    for n in range(min(4, len(parts)), 0, -1):
        if norm("".join(parts[:n])) in keys:
            return " ".join(parts[n:])
    return None


def product_like(url, keys):
    """Visszaad egy jel-cimket ('A:path-marker' ...) vagy None-t."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    segs = [s for s in path.split("/") if s]
    if not segs:
        return None
    low = [s.lower() for s in segs]
    if SKIP_EXT.search(segs[-1]):
        return None
    if any(s in SKIP_SEG for s in low):
        return None
    if any(low[i] == "page" for i in range(len(low) - 1)):
        return None
    last = re.sub(r"\.(php|html?|aspx)$", "", segs[-1], flags=re.I)
    if not last or last.lower() in MARKERS or last.isdigit():
        return None
    if re.match(r"^products?[.\-_]", last, re.I) and len(last) > 9:
        return "D:product-prefix"
    if any(s in MARKERS for s in low[:-1]):
        return "A:path-marker"
    if any(seg_is_maker(s, keys) for s in low[:-1]):
        return "B:maker-segment"
    rest = slug_maker_head(last, keys)
    if rest is not None:
        # A maradek a MODELLNEV. Egy blogcim slugja hosszabb ("roland-announces-
        # a-new-flagship-synthesizer"), ezert a hossz a fek. Merve: a bazisban
        # levo 280 lapos cim maradeka 1-5 szo.
        words = [w for w in re.split(r"[-_ ]+", rest) if w]
        if 1 <= len(words) <= 5:
            return "C:maker-slug"
    return None


# --- letoltes + cache ------------------------------------------------------
def fetch(url, timeout=25):
    try:
        r = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(timeout),
             "--max-filesize", str(MAX_BYTES), "-A", UA, url],
            capture_output=True, timeout=timeout + 10)
        return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def cache_path(domain, url):
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return CACHE / domain / f"{h}.xml"


def fetch_cached(domain, url, refresh=False):
    p = cache_path(domain, url)
    if p.exists() and not refresh:
        return p.read_text(encoding="utf-8", errors="replace"), True
    body = fetch(url)
    if body:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return body, False


def collect_urls(domain, entry_url, refresh=False, offline=False):
    """Osszes URL a sitemapbol, a sitemapindexet egy szinttel kovetve.
    offline=True eseten CSAK a cache-bol dolgozik (--recount)."""
    if offline and not cache_path(domain, entry_url).exists():
        return [], 0, False, True
    text, hit = fetch_cached(domain, entry_url, refresh)
    if not text:
        return [], 0, False, hit
    locs = LOC_RX.findall(text)
    if "<sitemapindex" not in text.lower():
        return locs, 0, False, hit
    subs = [u for u in locs if u.lower().endswith((".xml", ".xml.gz"))]
    capped = len(subs) > MAX_SUB_SITEMAPS
    urls, all_hit = [], hit
    for sub in subs[:MAX_SUB_SITEMAPS]:
        if offline and not cache_path(domain, sub).exists():
            continue
        if not cache_path(domain, sub).exists():
            time.sleep(PAUSE)
        body, h = fetch_cached(domain, sub, refresh)
        all_hit = all_hit and h
        if body:
            urls.extend(LOC_RX.findall(body))
    return urls, min(len(subs), MAX_SUB_SITEMAPS), capped, all_hit


# --- validacio -------------------------------------------------------------
def known_urls(con, domain):
    return [r[0] for r in con.execute(
        "SELECT DISTINCT source_url FROM instruments"
        " WHERE source_url LIKE '%'||?||'%' AND source_url IS NOT NULL", (domain,))]


def validate(con, verbose=True):
    """A detektor vizsgaja azon, amirol MAR TUDJUK a valaszt.

    Nem opcionalis, es a --all futas magatol lefuttatja: 2026-09-04-en a szamot
    elobb adtam tovabb, mint hogy lefuttattam volna azon, amirol mar volt
    igazsagunk, es Kristof egyetlen linkkel dontotte meg. Ez a lepes az, ami
    akkor kimaradt."""
    keys = maker_keys(con)
    rows = con.execute("""
        SELECT sd.domain,
               (SELECT COUNT(*) FROM instruments i WHERE i.source_url LIKE '%'||sd.domain||'%'),
               (SELECT COUNT(DISTINCT i.source_url) FROM instruments i
                  WHERE i.source_url LIKE '%'||sd.domain||'%')
        FROM source_domains sd
        WHERE sd.verdict='harvestable' AND sd.route='sitemap'
    """).fetchall()

    per_model, list_source, too_small, failed = [], [], [], []
    for domain, n_inst, n_url in rows:
        if not n_inst:
            continue
        if n_url < MIN_KNOWN_URLS:
            too_small.append((domain, n_inst, n_url))
            continue
        if n_url / n_inst < PER_MODEL_RATIO:
            list_source.append((domain, n_inst, n_url))
            continue
        urls = known_urls(con, domain)
        hit = sum(1 for u in urls if product_like(u, keys))
        recall = hit / len(urls)
        per_model.append((domain, n_inst, hit, len(urls), recall))
        if recall < RECALL_MIN:
            failed.append((domain, hit, len(urls), recall))

    if not verbose:
        return (not failed) if per_model else None

    print("--- VALIDACIO: felismeri-e a detektor a BIZONYITOTT hangszeroldalakat ---")
    for d, n_inst, hit, tot, rec in sorted(per_model, key=lambda r: -r[1]):
        mark = "ok   " if rec >= RECALL_MIN else "BUKTA"
        print(f"  {mark} {d:24} {hit:4}/{tot:<4} = {rec:.2f}  ({n_inst} hangszer)")
    for d, n_inst, n_url in list_source:
        print(f"  n.a.  {d:24} LISTA-forras: {n_inst} hangszer {n_url} oldalrol,"
              f" a sitemap-hozam ra nem ertelmes")
    for d, n_inst, n_url in too_small:
        print(f"  n.a.  {d:24} csak {n_url} ismert oldal, ez nem merce")
    if not per_model:
        print("nincs meg modell-szintu bizonyitott forras, a validacio nem eldontheto")
        return None
    tot_hit = sum(r[2] for r in per_model)
    tot_all = sum(r[3] for r in per_model)
    print(f"  osszesitve {len(per_model) - len(failed)}/{len(per_model)} forras atment,"
          f" recall {tot_hit}/{tot_all} = {tot_hit / tot_all:.3f}")
    return not failed


def audit(con, domain, sample=8):
    """Precizitas-ellenorzes: amit a detektor termeknek mond a sitemapban, de
    NINCS a bazisunkban -- annak letoltjuk a cimet, es kiirjuk. Ez az egyetlen
    resz, ami halozatot hasznal. A recall onmagaban nem eleg: egy detektor, ami
    mindent termeknek mond, 100% recallt er el es hasznalhatatlan."""
    keys = maker_keys(con)
    row = con.execute("SELECT route_url FROM source_domains WHERE domain=?", (domain,)).fetchone()
    if not row or not row[0]:
        print(f"{domain}: nincs sitemap-utvonal")
        return 1
    urls, _, _, _ = collect_urls(domain, row[0])
    have = set(known_urls(con, domain))
    cand = [u for u in urls if product_like(u, keys) and u not in have]
    print(f"{domain}: {len(urls)} URL, ebbol termek-jelolt es meg nincs nalunk: {len(cand)}")
    step = max(1, len(cand) // sample)
    for u in cand[::step][:sample]:
        time.sleep(PAUSE)
        html = fetch(u, timeout=20)
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:90] if m else "(nincs cim)"
        print(f"   {title}\n      {u}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="csak a detektor vizsgaja, meres nelkul")
    ap.add_argument("--recount", action="store_true",
                    help="ujraszamlalas a mar letoltott sitemapokbol, halozat nelkul")
    ap.add_argument("--refresh", action="store_true", help="cache megkerulese")
    ap.add_argument("--audit", metavar="DOMAIN", help="precizitas-ellenorzes egy domainen")
    ap.add_argument("--top", type=int, default=0, help="a legjobb N jelolt a mert adatbol")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--write", action="store_true", help="eredmeny DB-be irasa")
    args = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    if args.validate:
        ok = validate(con)
        con.close()
        return 0 if ok else 1
    if args.audit:
        rc = audit(con, args.audit)
        con.close()
        return rc
    if args.top:
        rows = con.execute("""
            SELECT domain, product_urls, sitemap_urls, COALESCE(inbound_links,0), harvester
            FROM source_domains
            WHERE verdict='harvestable' AND route='sitemap' AND product_urls > 0
            ORDER BY product_urls DESC LIMIT ?""", (args.top,)).fetchall()
        print(f"{'domain':30} {'termek':>7} {'osszes':>7} {'link':>5}  leszedo")
        for d, p, s, inb, h in rows:
            print(f"{d:30} {p:7} {s:7} {inb:5}  {h or '-'}")
        con.close()
        return 0

    keys = maker_keys(con)
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

    print(f"{'domain':30} {'osszes':>7} {'termek':>7} {'arany':>6}  megjegyzes")
    total_with, total_without = 0, 0
    for domain, url, _n, _inb in rows:
        urls, subs, capped, cached = collect_urls(
            domain, url, refresh=args.refresh, offline=args.recount)
        prods = [u for u in urls if product_like(u, keys)]
        note = ""
        if not urls:
            note = "nincs cache-elt sitemap" if args.recount else "nem jott sitemap"
        elif not prods:
            note = "NINCS termekoldal a sitemapban"
        elif len(prods) / len(urls) > 0.90:
            # Minden oldalnak van kategoria-, tag- es infooldala. Ha ez nincs,
            # az inkabb tulfedes, mint jo forras -- nezd meg --audit-tal.
            note = "gyanusan magas arany, ellenorizd: --audit " + domain
        if capped:
            note += f" (csak {MAX_SUB_SITEMAPS} al-sitemap olvasva)"
        if cached and urls:
            note += " [cache]"
        ratio = f"{len(prods) / len(urls):.2f}" if urls else "-"
        print(f"{domain:30} {len(urls):7} {len(prods):7} {ratio:>6}  {note}")
        sys.stdout.flush()
        if prods:
            total_with += 1
        else:
            total_without += 1
        if args.write:
            con.execute(
                "UPDATE source_domains SET product_urls=?, sitemap_urls=?, last_checked=?,"
                " note=COALESCE(note,'') || ? WHERE domain=?",
                (len(prods), len(urls), datetime.now(timezone.utc).isoformat(),
                 f" [sitemap-hozam merve {datetime.now(timezone.utc).date()}: "
                 f"{len(prods)}/{len(urls)}]", domain))
            con.commit()
        if not cached and not args.recount:
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
