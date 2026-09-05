#!/usr/bin/env python3
"""Ujra-feldolgozza a MAR TAROLT external_links sorokat hangszer-jeloltekke.

MIERT LETEZIK. Kristof, 2026-09-04: "ha van otleted, jobb osszefugges,
javasolj, epitsuk be es ha lehet visszamenoleg is csekkoljunk" es "amit lehet
fejlesztest ne csak memoriaban tarts, hanem epitsd a scriptbe, hogy ne
vesszen el tudas".

A konkret eset, amibol ez szuletett: a harvest_synthxl.py 2026-08-30-an
lefutott, 1091 modell-oldal linkjet eltarolta, a forras `harvested_at` mezoje
kitoltodott, es a forras ezzel "kesz" lett. Kozben a linkekben ott allt 683
olyan modell, amit a bazis nem ismer, es senki nem nezett ra ujra, mert a
leszedo mar lefutott egyszer. A kitoltott `harvested_at` befagyasztja a
forrast azon a szinten, ahol eloszor leszedtuk.

Ez a szkript NEM tolt le semmit. Amit mar egyszer megszereztunk, azt olvassa
ujra egy jobb parserrel. Ha egy leszedo kepessege bovul, ezt kell futtatni, es
a kimenet mondja meg, ert-e valamit a javitas: hany UJ modell latszik olyan
forrasbol, amit mar feldolgozottnak hittunk.

MIT NEM CSINAL. Nem ir evszamot es nem ir muszaki adatot: a link-alapu forras
csak azt bizonyitja, hogy a modell LETEZIK, es hogy melyik gyartoe. A synthxl
model-oldala peldaul se evszamot, se specet nem tartalmaz (2026-09-05-en
vegigneztem minden utvonalat: JSON-LD, tablazat, beagyazott JSON, meta).

Hasznalat:
  python3 db/reharvest_from_links.py --domain synthxl.com            # meres
  python3 db/reharvest_from_links.py --domain synthxl.com --show-scope
  python3 db/reharvest_from_links.py --domain synthxl.com --ingest
"""
import re
import sys
from html import unescape as _html_unescape
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"

# Ami NEM hangkelto eszkoz. Kristof scope-tesztje: a hangszer HANGOT KELT.
# A lista MERESSEL keszult, nem talalgatassal: a synthxl 683 ismeretlen
# modelljenek atnezesekor ezek a tipusok jottek elo (Alesis Quadraverb,
# Microverb, Nanoverb, Midiverb -> effekt; Matica 500/900, RA-100, RA-150 ->
# vegfok; MM-16 -> kevero). Ha uj tipust talalsz, IDE ird be, ne egy
# uzenetbe -- ez a lista az egyetlen hely, ahol ez a tudas megmarad.
NOT_SOUND_SOURCE = re.compile(
    r"\b("
    r"\w*verb\b|delay|compressor|limiter|equali[sz]er|crossover|"        # effekt
    r"amplifier|amp|matica|power ?amp|"                                   # erosito
    r"mixer|mixing|console|"                                              # kevero
    r"microphone|mic|preamp|"                                             # mikrofon
    r"recorder|cassette|tape deck|turntable|cd player|dat|"               # felvevo
    r"speaker|monitor|headphone|"                                         # hangszoro
    r"interface|patchbay|splitter|multi-?effect|effect processor|"        # studio
    r"processor|active monitor|"                                          # cimekbol mert
    r"footswitch|pedalboard|stand|case|bag|cover|power supply"            # tartozek
    r")\b", re.I)

# Ezek a szavak viszont EGYERTELMUEN hangkeltok, es feluliraljak a fentit
# (a "synthesizer amp" nem vegfok). Szandekosan szuk lista.
SOUND_SOURCE = re.compile(
    r"\b(synth|synthesi[sz]er|piano|organ|drum|sampler|sequencer|"
    r"keyboard|workstation|theremin|mellotron|clavinet|rhodes|vocoder)\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def maker_index(con):
    """gyartonev (kisbetus) -> manufacturer_id. A nevtortenet is benne van,
    mert a slug a KORABBI neven allhat (dave-smith-... -> Sequential)."""
    idx = {}
    for name, mid in con.execute("SELECT canonical_name, id FROM manufacturers"):
        idx[name.lower()] = mid
    for name, mid in con.execute("SELECT name, manufacturer_id FROM manufacturer_name_history"):
        idx.setdefault(name.lower(), mid)
    return idx


def split_slug(slug, idx):
    """('waldorf-pulse', idx) -> (manufacturer_id, 'pulse') vagy (None, slug).

    A gyarto a slug ELEJEN all, es tobb szavas is lehet (dave-smith-...),
    ezert a leghosszabb egyezest keressuk visszafele, nem az elsot."""
    parts = slug.split("-")
    for n in range(min(4, len(parts)), 0, -1):
        head = " ".join(parts[:n])
        for cand in (head, head.replace(" ", "")):
            for key, mid in idx.items():
                if cand == key or cand == key.replace(" ", "").replace("-", ""):
                    return mid, " ".join(parts[n:])
    return None, slug


# HAROM KIMENETEL, NEM KETTO. Ez a 2026-09-05-i meres eredmenye 686 synthxl
# cimen: 262 cimben van hangszer-szo es nincs ellen-szo, 179-ben forditva, es
# 245 cimbol EGYSZERUEN NEM DERUL KI ("Korg KMS 30", "Roland CR 5000 - CR 8000").
# A ketallapotu szuro ezt a 245-ot vagy mind beengedi (es akkor keverok es
# vegfokok kerulnek a bazisba), vagy mind kidobja (es akkor a CR-8000 dobgep
# vesz el). Egyik sem elfogadhato, ezert a harmadik allapot: "eldonthetetlen",
# ami NEM kerul be, de nem is vesz el -- kulon listat kap.
# NINCS BENNE "eurorack" ES "module", pedig kezenfekvo lenne. Meres, 2026-09-05:
# a synthxl cimekben az "Eurorack" a Behringer 90-es evekbeli KEVERO-szeriaja
# ("Behringer MX 1602 Eurorack", "MX 2804 EuroRack"), nem a modularis formatum.
# Ot keverot engedett volna be hangszerkent. A "module" ugyanigy ketertelmu
# ("Roland A 110 Midi Display"). Egy szot csak akkor tegyunk ide, ha a MERT
# eseteinkben egyertelmu volt -- a jelentese onmagaban nem eleg.
# A "groovebox" es a "multisampler" 2026-09-05-en kerult be, MERESSEL: az
# elektron.se tiz hardvere kozul a Model:Cycles es a Model:Samples cimeben a
# groovebox az EGYETLEN tipus-szo ("6 Track FM Based Groovebox"), a Tonverkeben
# a multisampler. Mindketto egyertelmuen hangkelto, es a "sampler" szoszegely
# miatt a "Multisampler" nem talalt bele. Ket eszkoz alt emiatt eldonthetetlenul,
# ugy hogy a cim vilagosan megmondta, mik.
INSTRUMENT_WORD = re.compile(
    r"\b(synthesi[sz]er|synth|piano|organ|drum|sampler|multi-?sampler|sequencer|"
    r"keyboard|groovebox|workstation|vocoder|theremin|mellotron|clavinet|rhodes|"
    r"accordion|arranger)\b", re.I)


# EGYERTELMU ELLEN-JELEK. Ezek felulirjak a hangszer-szavakat, mert a nevben
# ott allhat a hangszer, amihez a termek KESZULT, anelkul hogy az maga hangszer
# lenne. Meres, 2026-09-05, elektron.se 198 cim: a "Drum Spells - Sound Pack for
# Syntakt" cimben ket hangszer-szo is van (drum, syntakt), es egy hangminta-
# csomag. Ugyanigy a "Vintage Drum Machines" es az "Acoustic Drum Machines":
# mindketto sample pack, nem dobgep. Enelkul a lista negy csomagot engedett
# volna be hangszerkent egy gyarto sajat oldalarol.
DECISIVE_NOT = re.compile(
    r"(sound ?pack|sample ?pack|preset ?pack|sound ?set|soundset|expansion pack|"
    r"booster pack|patch pack|sticker pack|enamel pin|woven patch|"
    r"t-?shirt|tote bag|carry bag|carry sleeve|backpack|hoodie|"
    r"protective lid|power supply|\bpsu\b|rack mount kit|usb hub|"
    r"\bcable\b|\badapter\b|button cap|overbridge)", re.I)


def verdict(model, label, title=None):
    """'instrument' | 'not-instrument' | 'undecided'.

    A cim a donto jel, mert a MODELLNEV nem mondja meg, mi az eszkoz: az
    "mm 16 usb ux17" egy kevero, az "ra 100" egy vegfok, es egyikben sincs
    kapaszkodo. A cimben viszont ott all ("Alesis Matica 500 Amplifier").
    Ha nincs cim, csak a nevre tamaszkodhatunk, es akkor a legtobb eset
    eldonthetetlen -- ez igy oszinte."""
    # HTML-ENTITAS DEKODOLAS, MIELOTT BARMIT MERUNK. Ez nem kozmetika:
    # a nyers cimben allo "&amp;" az "amp" szot tartalmazza, az pedig a
    # NOT_SOUND_SOURCE listaban a VEGFOK jele. Meres, 2026-09-05: az Elektron
    # osszes olyan hardvere, aminek a leirasaban "&" van (Analog Rytm MKII,
    # Digitakt II, Syntakt, Tonverk), emiatt bukott el vagy lett
    # "eldonthetetlen" -- egy hangszer-adatbazis a sajat &-jelein vesztette
    # volna el a dobgepeit. A hibat az tette lathatatlanna, hogy a talalat
    # ERTELMESNEK latszott ("amp" -> erosito), csak eppen sosem az volt.
    title = _html_unescape(title or "")
    # A cim SZEGMENSEI, az utolso nelkul -- az utolso a marka ("| Elektron",
    # "| SynthXL - Service Manual"), es nem az eszkozrol szol.
    # MIERT NEM CSAK AZ ELSO SZEGMENS. Meres, 2026-09-05, elektron.se: a gyarto
    # sajat oldalan a keszulek TIPUSA a MASODIK szegmensben all
    # ("Analog Four MKII | Expressive 4 Voice Analog Synthesizer | Elektron"),
    # az elsoben csak a puszta modellnev. Az elso szegmensre nezve mind a tiz
    # Elektron hardver "eldonthetetlen" lett, kozben mind a tizrol kiirja a cim,
    # hogy mi az. A ketszegmensu cimeknel ez valtozatlanul az elso szegmens,
    # tehat a synthxl 249 talalata nem mozdul.
    segs = [x for x in (title or "").split("|") if x.strip()]
    text = " ".join(segs[:-1] if len(segs) > 1 else segs) or f"{model} {label}"
    if DECISIVE_NOT.search(title or "") or DECISIVE_NOT.search(f"{model} {label}"):
        return "not-instrument"
    has_instr = bool(INSTRUMENT_WORD.search(text))
    has_not = bool(NOT_SOUND_SOURCE.search(text))
    # A CSUPASZ NEV NEM BIZONYITEK. Egy egyszegmensu cim ("Vintage Drum
    # Machines - Elektron") csak a termek NEVE, nem a leirasa, es a nevben ott
    # allhat a hangszer-szo ugy, hogy a termek egy hangminta-csomag. Meres,
    # 2026-09-05: harom ilyen csomag ("Acoustic Drum Machines", "Vintage Drum
    # Machines", "Drum Enthusiast") csuszott volna be hangszerkent. A synthxl
    # 249 talalata ELLENBEN mind tobb-szegmensu cimbol jon (megmerve: 249/249),
    # tehat ez a szigoritas ott NULLA-ba kerul.
    # A harmadik allapot itt is a helyes valasz: nem engedjuk be, de nem is
    # dobjuk el -- az eldontesehez masik jel kell, nem a cim.
    if has_instr and not has_not and len(segs) < 2:
        return "undecided"
    if has_instr and not has_not:
        return "instrument"
    if has_not and not has_instr:
        return "not-instrument"
    return "undecided"


# --------------------------------------------------------------------------
# Cim-alapu ut. A modellnev nem mondja meg, mi az eszkoz; az oldal CIME igen.
# Egy keres oldalankent, lemezre cache-elve, tehat egyszer kell vegigmenni.
CACHE_ROOT = Path(__file__).resolve().parent / "cache"
UA = "Mozilla/5.0 (compatible; SynthsworldBot/1.0; kutatas, nem kereskedelmi)"
TITLE_RX = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def page_title(url, domain, refresh=False):
    """Az oldal <title> tartalma, lemezre cache-elve. Ures string, ha nem jott."""
    import subprocess
    import html as _html
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", url.rstrip("/").rsplit("/", 1)[-1])[:120]
    dest = CACHE_ROOT / f"{domain}-titles" / f"{slug}.txt"
    if dest.exists() and not refresh:
        return dest.read_text(encoding="utf-8", errors="replace").strip()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["curl", "-sS", "-L", "--max-time", "25",
                            "--max-filesize", "3000000", "-A", UA, url],
                           capture_output=True, timeout=40)
        body = r.stdout.decode("utf-8", errors="replace")
    except Exception:
        body = ""
    m = TITLE_RX.search(body)
    title = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    dest.write_text(title, encoding="utf-8")
    return title


# A cimbol a kategoria-szo: "Waldorf Pulse Synthesizer | SynthXL - ..." elso
# szakaszabol a tipus.
CATEGORY_WORDS = re.compile(
    r"\b(synthesi[sz]er|synth|piano|organ|drum machine|drum|sampler|sequencer|"
    r"keyboard|workstation|vocoder|arranger)\b", re.I)


def category_from_title(title):
    hits = CATEGORY_WORDS.findall(title.split("|")[0])
    return hits[-1].lower() if hits else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="pl. synthxl.com")
    ap.add_argument("--ingest", action="store_true", help="a jelolteket beirja")
    ap.add_argument("--show-scope", action="store_true",
                    help="listazza, mit szurt ki a scope-teszt (ellenorzeshez)")
    ap.add_argument("--limit", type=int, default=25, help="hany peldat mutasson")
    ap.add_argument("--titles", action="store_true",
                    help="oldalcimek lekerese (cache-elve) a scope ES a kategoria "
                         "eldontesehez -- ez a megbizhato ut, a modellnev nem eleg")
    ap.add_argument("--pause", type=float, default=0.7, help="szunet keresek kozott")
    args = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    idx = maker_index(con)

    known = {}
    for mid, name in con.execute("SELECT manufacturer_id, name FROM instruments"):
        known.setdefault(mid, set()).add(norm(name))

    links = con.execute(
        "SELECT url, COALESCE(label,'') FROM external_links WHERE url LIKE ?",
        (f"%{args.domain}/%",)).fetchall()

    slug_rx = re.compile(re.escape(args.domain) + r"/([^/?#]+)/?$")
    already = new = no_maker = out_of_scope = undecided = 0
    candidates, rejected, unsure = [], [], []

    for url, label in links:
        m = slug_rx.search(url)
        if not m:
            continue
        mid, model = split_slug(m.group(1), idx)
        if mid is None or not model.strip():
            no_maker += 1
            continue
        if norm(model) in known.get(mid, set()):
            already += 1
            continue
        title = ""
        if args.titles:
            import time as _t
            before = (CACHE_ROOT / f"{args.domain}-titles").exists()
            title = page_title(url, args.domain)
            if not before:
                _t.sleep(args.pause)
        v = verdict(model, label, title)
        if v == "not-instrument":
            out_of_scope += 1
            rejected.append((model, title or label, url))
            continue
        if v == "undecided":
            undecided += 1
            unsure.append((model, title or label, url))
            continue
        new += 1
        candidates.append((mid, model, url, category_from_title(title) if title else ""))

    print(f"forras: {args.domain}, tarolt link: {len(links)}")
    print(f"  a modell MAR megvan nalunk        : {already}")
    print(f"  UJ, hangkelto jelolt              : {new}")
    print(f"  kiszurve (bizonyitottan nem hangszer): {out_of_scope}")
    print(f"  ELDONTHETETLEN a cimbol             : {undecided}")
    print(f"  a gyarto nem ismerheto fel        : {no_maker}")

    if args.show_scope:
        print("\n--- amit a teszt KIZART (ezt nezd at, itt bukik a szuro) ---")
        for model, label, url in rejected[:args.limit]:
            print(f"    {model:30} {(label or '')[:60]}")
        print("\n--- ELDONTHETETLEN (ezekhez masodik jel kell, nem vesznek el) ---")
        for model, label, url in unsure[:args.limit]:
            print(f"    {model:30} {(label or '')[:60]}")
    else:
        print("\n--- UJ jeloltek, elso nehany ---")
        for mid, model, url, cat in candidates[:args.limit]:
            print(f"    [{mid}] {model:32} {cat or '(nincs kategoria)':14} {url}")

    if not args.ingest:
        print("\n  -- meres, semmi nem irodott; --ingest ir --")
        con.close()
        return 0

    now = datetime.now(timezone.utc).isoformat()
    note = (f"{args.domain} link-ujrafeldolgozas {now[:10]}: a modell LETEZESE es a "
            f"gyartoja biztos, evszam es muszaki adat NINCS ebbol a forrasbol.")
    for mid, model, url, cat in candidates:
        con.execute(
            "INSERT INTO instruments (manufacturer_id, name, category, source_url,"
            " created_at, review_status, review_note) VALUES (?,?,?,?,?, 'needs_review', ?)",
            (mid, model, cat or None, url, now, note))
    con.commit()
    print(f"\n  beirva: {len(candidates)} sor, mind needs_review jelolessel")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
