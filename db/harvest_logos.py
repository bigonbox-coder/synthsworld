#!/usr/bin/env python3
"""Logo-kereses gyartonkent, LETRAN: minden fok ott folytatja, ahol az elozo elakadt.

Miert kell: 2026-09-02-ig a logo-gyujtes kizarolag kezi (modell-)munka volt. A
`collect_logo.sh` csak egy MAR MEGTALALT cimet tolt le; hogy melyik az a cim,
azt eddig mindig egy modell kereste ki. Ez a script a keresest is gepiesiti,
tokenkoltseg nelkul. Kristof kerdese inditotta: "ez script token nelkul?"

A LETRA (Kristof kerese: ne alljunk meg az elso forrasnal):
  1. Wikidata P154 (logo image)      -- a legbiztosabb, mert az azonossag ellenorizheto
  2. Wikipedia infobox `logo =`      -- sok cegnel ki van tolve, ha a Wikidataban nincs
  3. A gyarto SAJAT honlapja         -- a legjobb provenancia, ha tudjuk a cimet
  4. Wayback (megszunt cegek)        -- ugyanaz a 3. fok egy archiv pillanatkepen
  5. SearXNG kepkereses              -- SZANDEKOSAN NINCS MEGIRVA, lasd lentebb

AZONOSSAG-ELLENORZES, ez a script leglenyege. A puszta nevkereses TEVES ceget
ad: merve 2026-09-02-en az "Arturia" egy szivacsnemzetseget, a "Fairlight" egy
1985-os videojatekot, a "Bontempi" egy vezeteknevet hozott elso talalatkent.
Ezeknel veletlenul nem volt logo -- ha lett volna, a script NEMAN rossz logot
tett volna be. Ezert egy Wikidata-talalat CSAK akkor fogadhato el, ha:
  (a) a P856 (hivatalos honlap) domainje egyezik a nalunk tarolttal,  VAGY
  (b) a P31 (instance of) szerint ceg/szervezet ES a cimke egyezik a nevunkkel.
Ami egyiken sem megy at, az NEM kap sort, hanem a jelentes-fajlba kerul kezi
munkara. A "nem tudtuk megnezni" nem ugyanaz, mint a "megneztuk, nincs".

HAROM ALLAPOT, ahogy az admin panel varja (lasd admin/server.py logo_status):
  sor + lokalis fajl  -> "megvan"
  sor, fajl nelkul    -> "kerestunk, nem talaltunk"
  NINCS sor           -> "meg meg sem neztuk"
Ezert fut le vegig a letra MIELOTT barmit beirna: egy ures sor azt allitja,
hogy tenylegesen kerestunk.

Amit NEM csinal:
  - Drive-feltoltes (ahhoz MCP kell, ez sima script). A `drive_file_url` NULL
    marad, a lokalis masolat viszont elkeszul, es a publikus oldal (`site/
    generate.py`) is abbol dolgozik. A Drive-mester potlasa kesobbi kezi lepes.
  - Evszamot SOHA nem talal ki (`start_year`/`end_year` NULL marad).
  - Nem hagy jova semmit: minden uj sor `logo_review_status = NULL`, vagyis a
    panel "Jovahagyando" csempejere kerul. Publikus oldalra kerulo kep, Kristof
    donti el egyesevel.
  - 5. fok (SearXNG): a kepkereses jelolteket ad, nem bizonyitekot, es ebben a
    projektben minden allitas forrast hordoz. Kepkeresesbol nem lehet
    megallapitani, hogy a talalt kep tenyleg a CEG logoja-e. Marad kezi.

Hasznalat:
  python3 db/harvest_logos.py --dry-run              # csak mutatja, mit tenne
  python3 db/harvest_logos.py --ingest               # a 25 kikutatott gyartora
  python3 db/harvest_logos.py --ingest --limit 5
  python3 db/harvest_logos.py --dry-run --only Casio
  python3 db/harvest_logos.py --ingest --include-unresearched
"""

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
LOGO_DIR = HERE.parent / "admin" / "static" / "logos"
REPORT_DIR = HERE / "batches"
COLLECT = HERE / "collect_logo.sh"
TMP = Path("/tmp/synthlogos")

UA = ("SynthsworldResearch/0.1 (synthsworld museum database; "
      "contact via kristof.gal@gmail.com)")

WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# P31 (instance of) ertekek, amik CEGET/SZERVEZETET jelentenek. Ezen a listan
# bukik el a szivacsnemzetseg, a videojatek es a vezeteknev.
COMPANY_QIDS = {
    "Q4830453",   # business
    "Q783794",    # company
    "Q6881511",   # enterprise
    "Q891723",    # public company
    "Q210167",    # video game developer -- nem ide valo, lasd lent
    "Q43229",     # organization
    "Q167037",    # corporation
    "Q1058914",   # software company
    "Q18388277",  # technology company
    "Q3778211",   # legal person
    "Q2085381",   # publisher
    "Q1786882",   # sole proprietorship
    "Q728646",    # limited company
    "Q15911314",  # association
    "Q219577",    # holding company
    "Q740752",    # Aktiengesellschaft
    "Q1364180",   # GmbH-fele
    "Q10689397",  # television production company
    "Q4830453",
}
# A Q210167 (video game developer) SZANDEKOSAN bent van: a Fairlight-fele
# nevutkozesnel a videojatek MAGA nem ceg (az Q7889 = video game), a fejleszto
# viszont valodi ceg lenne. A szures igy nem a jatekot fogadja el, hanem csak
# egy ceget -- a nevegyezes es a honlap-egyezes donti el a tobbit.

# Hangszer-ipari kapaszkodo: ha a ceg P452 (industry) vagy P1056 (product)
# mezoje hangszerre mutat, az onmagaban eros jel, hogy a JO ceget talaltuk.
INSTRUMENT_HINT_QIDS = {
    "Q1327500",   # electronic musical instrument
    "Q163829",    # synthesizer
    "Q831698",    # analog synthesizer
    "Q320002",    # sampler
    "Q1327327",   # drum machine
    "Q34379",     # musical instrument
    "Q2334061",   # musical instrument manufacturing
    "Q746359",    # keyboard instrument
}


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Cegformak es altalanos utotagok, amik ket nev azonossagat nem befolyasoljak.
# "Waldorf Music" es "Waldorf" ugyanaz a ceg; "Linn" es "Linnaeus University"
# NEM az. Ezert szo szerinti utotag-levagas, NEM reszsztring-egyezes.
NAME_SUFFIXES = {
    "inc", "inc.", "ltd", "ltd.", "limited", "llc", "plc", "corp", "corp.",
    "corporation", "company", "co", "co.", "gmbh", "ag", "kg", "mbh", "ab",
    "as", "a/s", "oy", "bv", "b.v.", "nv", "srl", "s.r.l.", "spa", "s.p.a.",
    "sa", "sas", "kk", "k.k.", "pty", "gbr", "ohg", "dmi",
    "music", "musical", "instruments", "instrument", "electronics",
    "electronic", "audio", "sound", "systems", "technologies", "technology",
    "international", "group", "holding", "holdings", "industries",
}


def name_core(s):
    """A nev magja: a cegformak es altalanos utotagok nelkul, normalizalva."""
    toks = [t for t in re.split(r"[\s,]+", (s or "").lower()) if t]
    while toks and toks[-1].strip(".") in NAME_SUFFIXES:
        toks.pop()
    return norm(" ".join(toks)) or norm(s)


def names_match(ours, theirs):
    """SZIGORU nevegyezes. A korabbi reszsztring-szabaly a "Linn" nevre a
    Linne-egyetemet fogadta el (2026-09-02, elso eles futas: a Linn logojanak
    a Linnaeus University logoja kerult be, kezzel kellett visszavonni). Egy
    rovid nev SOK hosszabb nevben benne van, tehat a tartalmazas nem bizonyitek."""
    a, b = norm(ours), norm(theirs)
    if not a or not b:
        return False
    if a == b:
        return True
    return name_core(ours) == name_core(theirs)


def domain(url):
    """Osszehasonlithato domain: sema, www es zaro per nelkul, kisbetusen."""
    if not url:
        return ""
    d = re.sub(r"^https?://", "", url.strip().lower())
    d = d.split("/")[0].split("?")[0]
    return d[4:] if d.startswith("www.") else d


def curl(url, binary=False, max_time=45):
    """Egy kimenet, egy helyen. A binaris ag byte-ot ad vissza, nem szoveget."""
    cmd = ["curl", "-sSL", "--max-time", str(max_time), "-A", UA, url]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def api_json(url):
    raw = curl(url)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------- 1. fok: Wikidata

def wd_search(name, limit=5):
    url = (f"{WD_API}?action=wbsearchentities&format=json&language=en&uselang=en"
           f"&type=item&limit={limit}&search={urllib.parse.quote(name)}")
    d = api_json(url) or {}
    return [h["id"] for h in (d.get("search") or [])]


def wd_entities(qids):
    if not qids:
        return {}
    url = (f"{WD_API}?action=wbgetentities&format=json&ids={'|'.join(qids)}"
           f"&props=claims|labels|descriptions|sitelinks")
    d = api_json(url) or {}
    return d.get("entities") or {}


def claim_values(entity, prop):
    """A P-mezo ertekei egyszeru listakent (QID vagy string vagy fajlnev)."""
    out = []
    for c in (entity.get("claims") or {}).get(prop, []):
        snak = c.get("mainsnak") or {}
        if snak.get("snaktype") != "value":
            continue
        v = (snak.get("datavalue") or {}).get("value")
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
        elif isinstance(v, str):
            out.append(v)
    return out


def identify(name, our_site):
    """A JO Wikidata-tetel megkeresese, vagy None.

    Ket fuggetlen bizonyitek, es barmelyik eleg:
      - honlap-egyezes: a P856 domainje ugyanaz, mint a nalunk tarolt cim
      - ceg + nev: P31 szerint ceg/szervezet ES a cimke egyezik a nevunkkel
        (a hangszer-ipari P452/P1056 onmagaban is elfogadja a ceget)
    Visszaad: (qid, entity, indok) vagy (None, None, ok-a-visszautasitasnak).
    """
    qids = wd_search(name)
    time.sleep(0.6)
    if not qids:
        return None, None, "a Wikidata nem ismeri ezt a nevet"
    ents = wd_entities(qids)
    time.sleep(0.6)
    fallback = None
    for qid in qids:                     # a talalati sorrend szamit
        e = ents.get(qid)
        if not e:
            continue
        label = ((e.get("labels") or {}).get("en") or {}).get("value", "")
        sites = [domain(s) for s in claim_values(e, "P856")]
        p31 = set(claim_values(e, "P31"))
        industry = set(claim_values(e, "P452")) | set(claim_values(e, "P1056"))

        if our_site and domain(our_site) and domain(our_site) in sites:
            return qid, e, f"honlap-egyezes ({domain(our_site)})"

        name_ok = names_match(name, label)
        if not name_ok:
            continue
        if industry & INSTRUMENT_HINT_QIDS:
            return qid, e, "nevegyezes + hangszeripari cegprofil"
        if p31 & COMPANY_QIDS:
            return qid, e, "nevegyezes + ceg/szervezet tipus"
        if fallback is None:
            desc = ((e.get("descriptions") or {}).get("en") or {}).get("value", "")
            fallback = f"{qid} nevben egyezik, de nem ceg ({desc or 'nincs leiras'})"
    return None, None, fallback or "egyik talalat sem azonosithato biztosan"


def rung_wikidata(entity):
    """P154 -> Commons fajl kozvetlen cime."""
    files = claim_values(entity, "P154")
    if not files:
        return None
    f = files[0]
    return COMMONS_FILEPATH + urllib.parse.quote(f.replace(" ", "_"))


# --------------------------------------------------------------- 2. fok: Wikipedia

WIKI_LOGO_RE = re.compile(
    r"\|\s*logo\w*\s*=\s*(?:\[\[)?\s*(?:File|Image|Fajl|Kep)?\s*:?\s*"
    r"([^|\]\n<]+?\.(?:svg|png|jpg|jpeg|gif))",
    re.IGNORECASE)


def rung_wikipedia(entity):
    """Az infobox `logo =` mezoje. Az azonossag az 1. fokrol OROKLODIK: a
    szocikket a mar ELFOGADOTT Wikidata-tetel sitelinkjebol vesszuk, nem
    nevkeresesbol -- kulonben visszajonne ugyanaz a nevutkozes-csapda."""
    sitelinks = entity.get("sitelinks") or {}
    for key in ("enwiki", "dewiki", "itwiki", "frwiki", "jawiki", "svwiki",
                "ruwiki", "huwiki", "eswiki", "nlwiki"):
        sl = sitelinks.get(key)
        if not sl:
            continue
        lang = key[:-4]
        title = urllib.parse.quote(sl["title"].replace(" ", "_"))
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=parse&format=json"
               f"&prop=wikitext&section=0&redirects=1&page={title}")
        d = api_json(url) or {}
        time.sleep(0.6)
        text = (((d.get("parse") or {}).get("wikitext") or {}).get("*")) or ""
        m = WIKI_LOGO_RE.search(text)
        if m:
            fname = m.group(1).strip()
            return COMMONS_FILEPATH + urllib.parse.quote(fname.replace(" ", "_"))
    return None


# ------------------------------------------------------- 3-4. fok: sajat honlap

IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w[\w:-]*)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
OG_RE = re.compile(
    r'<meta[^>]+property\s*=\s*["\']og:image["\'][^>]*content\s*=\s*["\']([^"\']+)',
    re.IGNORECASE)
ICON_RE = re.compile(
    r'<link[^>]+rel\s*=\s*["\'][^"\']*icon[^"\']*["\'][^>]*>', re.IGNORECASE)


def absolutise(src, base):
    if not src:
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("data:"):
        return None
    base = base.rstrip("/")
    return base + ("" if src.startswith("/") else "/") + src


def logo_candidates_from_html(html, base):
    """Sorrend = bizalom. Eloszor ami kimondja magarol hogy logo, aztan a
    megosztasi elonezet, vegul a vektoros ikon. Az .ico-t kihagyjuk: 32 pixeles
    favicon nem logo, es tobbet artana a felulet minosegenek mint amennyit er."""
    out = []
    for tag in IMG_RE.findall(html or ""):
        attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
        blob = " ".join([attrs.get("class", ""), attrs.get("id", ""),
                         attrs.get("alt", ""), attrs.get("src", "")]).lower()
        if "logo" in blob:
            u = absolutise(attrs.get("src") or attrs.get("data-src"), base)
            if u:
                out.append(u)
    m = OG_RE.search(html or "")
    if m:
        u = absolutise(m.group(1), base)
        if u:
            out.append(u)
    for tag in ICON_RE.findall(html or ""):
        attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
        href = attrs.get("href", "")
        if href.lower().endswith(".svg"):
            u = absolutise(href, base)
            if u:
                out.append(u)
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:4]


def rung_website(site):
    html = curl(site, max_time=30)
    if not html:
        return None
    cands = logo_candidates_from_html(html, site)
    return cands[0] if cands else None


def rung_wayback(site):
    """Ugyanaz a keres egy archiv pillanatkepen. A megszunt cegeknel ez az
    egyetlen ut a sajat logojukhoz."""
    d = api_json("https://archive.org/wayback/available?url="
                 + urllib.parse.quote(domain(site or ""))) or {}
    time.sleep(0.6)
    snap = (((d.get("archived_snapshots") or {}).get("closest") or {}).get("url"))
    if not snap:
        return None
    html = curl(snap, max_time=45)
    if not html:
        return None
    cands = logo_candidates_from_html(html, snap)
    return cands[0] if cands else None


# ------------------------------------------------------------------- letoltes

def fetch_logo_file(url, slug):
    """A collect_logo.sh-t hasznaljuk, nem irjuk ujra: az ffmpeg-varazslat
    maradjon EGY helyen. Visszaad: a letoltott fajl utja, vagy None."""
    for old in TMP.glob(f"{slug}.*"):
        old.unlink()
    r = subprocess.run(["bash", str(COLLECT), url, slug],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    files = sorted(TMP.glob(f"{slug}.*"))
    if not files:
        return None
    f = files[0]
    # Egy 1 kB alatti "logo" gyakorlatilag mindig hibaoldal vagy nyomkoveto pixel.
    if f.stat().st_size < 1024:
        f.unlink()
        return None
    return f


# ----------------------------------------------------------------------- main

def targets(con, args):
    sql = """SELECT m.id, m.canonical_name, m.official_website, m.status,
                    m.confidence_level
             FROM manufacturers m
             LEFT JOIN manufacturer_logos l ON l.manufacturer_id = m.id
             WHERE l.id IS NULL"""
    params = []
    if not args.include_unresearched:
        sql += " AND m.confidence_level != 'unresearched'"
    if args.only:
        sql += " AND m.canonical_name LIKE ?"
        params.append(f"%{args.only}%")
    sql += " ORDER BY m.canonical_name"
    rows = con.execute(sql, params).fetchall()
    return rows[:args.limit] if args.limit else rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None, help="csak az ezt tartalmazo nevre")
    ap.add_argument("--include-unresearched", action="store_true",
                    help="a meg kikutatatlan stubokra is (alapbol kihagyja: "
                         "ott elobb maga a ceg kell, nem a logoja)")
    args = ap.parse_args()
    if not (args.dry_run or args.ingest):
        ap.print_help()
        return 1

    TMP.mkdir(parents=True, exist_ok=True)
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = targets(con, args)
    print(f"{len(rows)} gyarto logo nelkul"
          f"{' (a kikutatatlanokkal egyutt)' if args.include_unresearched else ''}\n")

    stats = {"talalt": 0, "nincs": 0, "azonosithatatlan": 0}
    report = []

    for r in rows:
        mid, name = r["id"], r["canonical_name"]
        our_site = r["official_website"]
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        print(f"- {name}")

        qid, ent, why = identify(name, our_site)
        url = source_kind = None
        site_from_wd = None

        if ent:
            print(f"    azonositva: {qid} -- {why}")
            sites = claim_values(ent, "P856")
            site_from_wd = sites[0] if sites else None
            url = rung_wikidata(ent)
            if url:
                source_kind = "wikidata P154"
            else:
                url = rung_wikipedia(ent)
                if url:
                    source_kind = "wikipedia infobox"
        else:
            print(f"    NEM azonosithato: {why}")

        site = our_site or site_from_wd
        if not url and site:
            url = rung_website(site)
            if url:
                source_kind = "hivatalos honlap"
            elif r["status"] in ("defunct", "acquired", "unknown"):
                url = rung_wayback(site)
                if url:
                    source_kind = "wayback pillanatkep"

        if not url:
            # Ket kulonbozo kimenet, es a kulonbseg szamit. Ha azonositottuk a
            # ceget es vegigmentunk a letran: tenylegesen KERESTUNK, jarjon a
            # sor. Ha meg azonositani sem tudtuk: nem kerestunk rendesen, nem
            # allithatjuk az ellenkezojet -- marad "meg meg sem neztuk".
            if ent or site:
                stats["nincs"] += 1
                print("    vegigmentunk a letran, nincs logo -> ures sor")
                if args.ingest:
                    con.execute(
                        "INSERT INTO manufacturer_logos (manufacturer_id, "
                        "drive_file_url, source_url) VALUES (?, NULL, NULL)",
                        (mid,))
                    con.commit()
            else:
                stats["azonosithatatlan"] += 1
                print("    nem azonosithato -> kezi munka, sort nem irok")
                report.append({"manufacturer_id": mid, "name": name,
                               "reason": why, "our_site": our_site})
            continue

        print(f"    {source_kind}: {url[:88]}")
        if args.dry_run:
            stats["talalt"] += 1
            continue

        f = fetch_logo_file(url, slug)
        if not f:
            print("    a letoltes nem sikerult -> kezi munka, sort nem irok")
            stats["azonosithatatlan"] += 1
            report.append({"manufacturer_id": mid, "name": name,
                           "reason": f"a talalt cim nem toltheto le: {url}",
                           "our_site": our_site})
            continue

        # Eloszor a sor, mert a lokalis fajl neve a SOR azonositoja
        # (admin/static/logos/logo-<logo_id>.<ext>, lasd a projekt skilljet).
        cur = con.execute(
            "INSERT INTO manufacturer_logos (manufacturer_id, drive_file_url, "
            "start_year, end_year, logo_review_status, source_url) "
            "VALUES (?, NULL, NULL, NULL, NULL, ?)", (mid, url))
        logo_id = cur.lastrowid
        dest = LOGO_DIR / f"logo-{logo_id}{f.suffix}"
        try:
            shutil.copy(f, dest)
        except Exception as exc:
            con.rollback()
            print(f"    a masolas elhasalt ({exc}) -> a sort visszavontam")
            stats["azonosithatatlan"] += 1
            continue

        # A P856 visszairasa, ha nalunk meg nem volt: a kovetkezo futasnak mar
        # lesz honlapja a 3. fokhoz, es a domain-merohoz is ez kell.
        if site_from_wd and not our_site:
            con.execute("UPDATE manufacturers SET official_website=?, updated_at=? "
                        "WHERE id=?", (site_from_wd, now_iso(), mid))
            print(f"    hivatalos honlap potolva: {site_from_wd}")

        con.commit()
        stats["talalt"] += 1
        print(f"    -> {dest.name} (jovahagyando)")

    con.close()

    if report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / f"logo-harvest-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(f"\nAmit a gep nem tudott lezarni, fajlban: {out}")

    print(f"\nlogo megvan: {stats['talalt']} | kerestunk, nincs: {stats['nincs']} "
          f"| kezi munka marad: {stats['azonosithatatlan']}")
    if args.dry_run:
        print("(dry-run: semmi nem irodott az adatbazisba)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
