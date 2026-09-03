#!/usr/bin/env python3
"""EMUMANIA: E-mu-specifikus archivum, gepenkent adatlap-tablazattal.

Kristof adta at 2026-09-03 egy Proteus MPS-linkkel, majd: "mehet a leszedo".

MIERT EZ AZ OLDAL
=================
Egyetlen gyartora szakosodott archivum, es minden gep-oldalan UGYANAZ a
tablazat all: ROM-meret, mintavetel, preset-szamok, hangszerek szama,
szolamszam, MIDI-csatornak, szurok, effektek, kimenetek, billentyuszam. Ez
strukturalt adat, nem proza, tehat parserrel kiolvashato, modell nelkul.

A robots.txt mindent enged (a Yoast-blokk ures Disallow-t ad). A sitemapbol
139 cim jon, ebbol 116 "emu-" kezdetu, es ~45 valodi gep-oldal. A tobbi
ROM-kartya, sample-konyvtar es kategoria-lap, azok NEM hangszerek.

KET STRUKTURALT REteg, ES MIND A KETTO KELL
===========================================
1. JSON-LD (schema.org) a lap fejeben: a nev es egy leiras, amiben gyakran ott
   az EVSZAM is, kimondva: "Released in 1989, Proteus/1 was the first rack
   mountable synth manufactured by E-MU". Ez valodi megjelenesi ev, nem
   hirdetes-ev, tehat beirhato.
2. A "TECHNICAL SPECIFICATION" blokk a torzsben, "Felirat: ertek" parokkal.

A SZURES, ami eldonti, mi hangszer
==================================
A lap CIME mondja meg: Sound Module / Keyboard / Command Station / Command
Module vegzodes = gep. ROM Card, Preset Library, tobbes szamu kategoria-lap
(Sound Modules, Keyboards) = nem gep. Ezen felul kell a spec-blokk is: ami
nelkul erkezik, az nem adatlap.

AMIT NEM IR FELUL
=================
Evszamot csak akkor ir, ha nalunk MEG NINCS. A spec-ertekek nyersen kerulnek
be (instrument_specs, 0033), forras-URL-lel egyutt, tehat ha egy masik forras
mast mond, az ellentmondas latszik, nem tunik el.

Hasznalat:
  python3 db/harvest_emumania.py --fetch    # sitemap + lapok a cache-be
  python3 db/harvest_emumania.py --parse    # mit talalt, mit nem parositott
  python3 db/harvest_emumania.py --ingest   # iras: spec, link, evszam, uj sor
"""

import argparse
import html
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

from maker_lookup import MakerLookup, norm

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
CACHE = HERE / "cache" / "emumania"
SITEMAP = "https://www.emumania.net/page-sitemap.xml"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
SOURCE = "emumania"
DOMAIN = "emumania.net"
MAKER = "E-mu"
PAUSE = 2.5

# A cim vegzodese mondja meg, gep-e a lap. Egyes szam: egy termek. A tobbes
# szamu alak (Sound Modules) kategoria-lap, az kimarad.
FORMS = {
    "sound module": "module",
    "command module": "module",
    "command station": "module",
    "keyboard": "keyboard",
}
SPEC_START = re.compile(r"TECHNICAL SPECIFICATIONS?", re.I)
# "Released in 1989", "Introduced in 1994" -- a leirasban kimondott evszam.
YEAR_SAID = re.compile(r"\b(?:released|introduced|launched)\s+in\s+(19\d\d|20[0-2]\d)", re.I)
FIELDS = {
    "rom size": "rom_size", "sample rate/bitrate": "sample_rate",
    "presets": "presets", "instruments": "instrument_count",
    "polyphony": "polyphony", "midi channels": "midi_channels",
    "filters": "filters", "fx": "fx", "midi ports": "midi_ports",
    "audio outs": "audio_outs", "digital outs": "digital_outs",
    "keys": "keys", "sequencer": "sequencer", "arpeggiator": "arpeggiator",
    "ram size": "ram_size", "flash rom": "flash_rom",
}


def get(url, path):
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    time.sleep(PAUSE)
    return body


def page_urls():
    xml = get(SITEMAP, CACHE / "page-sitemap.xml")
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    return [u for u in urls if "/emu-" in u]


def slug(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def parse(url, body):
    """A lapbol: nev, forma, evszam-allitas, spec-parok. None, ha nem gep."""
    title = None
    m = re.search(r'"@type":"WebPage".*?"name":"(.*?)"', body, re.S)
    if m:
        title = json.loads(f'"{m.group(1)}"')
    if not title:
        m = re.search(r"(?is)<title>(.*?)</title>", body)
        title = html.unescape(re.sub(r"\s*[|-]\s*E-?MU.*$", "", m.group(1))) if m else None
    if not title:
        return None
    t = title.strip()
    form = None
    for suffix, kind in FORMS.items():
        if t.lower().endswith(suffix):
            form = (suffix, kind)
            t = t[: -len(suffix)].strip()
            break
    if not form:
        return None
    name = re.sub(r"^E-?MU\s+", "", t, flags=re.I).strip()
    if not name:
        return None

    desc = ""
    m = re.search(r'"description":"(.*?)","(?:breadcrumb|inLanguage)"', body, re.S)
    if m:
        try:
            desc = json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            desc = ""
    ysaid = YEAR_SAID.search(desc)

    # A spec-blokk: a "TECHNICAL SPECIFICATION" felirattol a lap aljaig
    # cimkek nelkul, "Felirat: ertek" parokra bontva.
    # A felirat TOBBSZOR is elofordulhat: a lap fejeben, a meta-leirasban es a
    # JSON-LD-ben is ott lehet a szoveg. Az elso talalat ezert gyakran a fejbe
    # esik, ahol nincs tablazat. Ezert MINDEN talalatot megprobalunk, es a
    # legtobb mezot ado nyer. (Igy jott elo hat lap: Vintage Pro, Orbit-3,
    # Proteus Custom, Turbo Phatt, Virtuoso 2000, XL-1 Turbo.)
    specs = {}
    for m in SPEC_START.finditer(body):
        found = _specs_at(body, m.end())
        if len(found) > len(specs):
            specs = found
    # Spec-tablazat nelkuli termekoldalt sem dobunk el: a lap maga, a neve es a
    # leirasa igy is bizonyitek, csak muszaki adat nem jon vele.
    return {"url": url, "name": name, "form": form[1], "form_label": form[0],
            "title": title, "desc": desc,
            "year": int(ysaid.group(1)) if ysaid else None, "specs": specs}


def _specs_at(body, pos):
    """Egy "TECHNICAL SPECIFICATION" talalat utani blokk kiolvasasa."""
    specs = {}
    if True:
        seg = body[pos: pos + 4000]
        text = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", seg))
        lines = [x.strip() for x in text.split("\n") if x.strip()]
        # A felirat es az ertek KULON sorban all, mert tag valasztja el oket
        # ("<strong>ROM Size:</strong> 4MB" -> "ROM Size:", "4MB"). Az elso
        # valtozat egy sorban kereste a kettospontot, es ezert 116 lapbol
        # egyet ismert fel. Mindket alakot kezeljuk.
        i = 0
        while i < len(lines):
            line = lines[i]
            label = value = None
            if line.endswith(":") and i + 1 < len(lines) and not lines[i + 1].endswith(":"):
                label, value = line[:-1].strip(), lines[i + 1].strip()
                i += 2
            elif ":" in line:
                a, _, b = line.partition(":")
                if b.strip():
                    label, value = a.strip(), b.strip()
                i += 1
            else:
                i += 1
            if not label or not value or len(label) > 40:
                continue
            key = FIELDS.get(label.lower())
            if not key:
                if not re.fullmatch(r"[A-Za-z][A-Za-z /&-]{1,30}", label):
                    continue
                key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            specs.setdefault(key, (label, value))
    return specs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    args = ap.parse_args()

    urls = page_urls()
    print(f"emu- lap a sitemapben: {len(urls)}")
    pages = []
    for u in urls:
        body = get(u, CACHE / f"{slug(u)}.html")
        p = parse(u, body)
        if p:
            pages.append(p)
    print(f"gep-adatlap (cim + spec-blokk alapjan): {len(pages)}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    makers = MakerLookup(con)
    mid = makers.find(MAKER)
    if not mid:
        raise SystemExit(f"nincs ilyen gyarto: {MAKER}")
    ours = {norm(r["name"]): r["id"] for r in
            con.execute("SELECT id, name FROM instruments WHERE manufacturer_id=?", (mid,))}

    matched = [(p, ours[norm(p["name"])]) for p in pages if norm(p["name"]) in ours]
    missing = [p for p in pages if norm(p["name"]) not in ours]
    print(f"parositva a mar meglevo sorral: {len(matched)}")
    print(f"nalunk MEG NINCS: {len(missing)}")
    withyear = [p for p in pages if p["year"]]
    print(f"kimondott evszam a leirasban: {len(withyear)}")

    if args.parse:
        for p in missing:
            print(f'  UJ  {p["name"]} ({p["form_label"]}) {p["year"] or "?"} '
                  f'-- {len(p["specs"])} mezo')
        for p, iid in matched[:8]:
            print(f'  van {p["name"]} -> #{iid}, {len(p["specs"])} mezo')

    if args.ingest:
        spec_rows = links = years = created = 0
        for p in pages:
            iid = ours.get(norm(p["name"]))
            if iid is None:
                # Uj sor. A bizonyitek egy sajat termekoldal spec-tablazattal,
                # ezert nem kap jelolest; az evszam csak akkor, ha kimondtak.
                cur = con.execute(
                    """INSERT INTO instruments (manufacturer_id, name, year, category,
                                                technology, source_url, review_note)
                       VALUES (?, ?, ?, ?, 'digital', ?, ?)""",
                    (mid, p["name"], p["year"], p["form"], p["url"],
                     f'[emumania {time.strftime("%Y-%m-%d")}] Sajat termekoldalrol, '
                     f'adatlap-tablazattal. {p["desc"][:400]}'))
                iid = cur.lastrowid
                ours[norm(p["name"])] = iid
                created += 1
            elif p["year"]:
                row = con.execute("SELECT year FROM instruments WHERE id=?", (iid,)).fetchone()
                if row["year"] is None:
                    con.execute("UPDATE instruments SET year=?, review_note="
                                "COALESCE(review_note,'')||? WHERE id=?",
                                (p["year"],
                                 f' [emumania {time.strftime("%Y-%m-%d")}] Evszam a forras '
                                 f'kimondott allitasabol: "{p["desc"][:160]}" {p["url"]}',
                                 iid))
                    years += 1
            for key, (label, value) in p["specs"].items():
                cur = con.execute(
                    """INSERT OR IGNORE INTO instrument_specs
                       (instrument_id, field, label, value, source_url, source_name)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (iid, key, label, value, p["url"], SOURCE))
                spec_rows += cur.rowcount
            ex = con.execute("SELECT 1 FROM external_links WHERE instrument_id=? AND url=?",
                             (iid, p["url"])).fetchone()
            if not ex:
                con.execute(
                    """INSERT INTO external_links (manufacturer_id, instrument_id, url, domain,
                                                   label, link_type, found_on, source_name)
                       VALUES (?, ?, ?, ?, ?, 'spec', ?, ?)""",
                    (mid, iid, p["url"], DOMAIN, f'{p["title"]} -- adatlap', SITEMAP, SOURCE))
                links += 1
        con.execute("UPDATE source_domains SET harvester='harvest_emumania', "
                    "harvested_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=?", (DOMAIN,))
        con.commit()
        print(f"\nuj hangszer: {created}, spec-ertek: {spec_rows}, "
              f"uj link: {links}, potolt evszam: {years}")


if __name__ == "__main__":
    main()
