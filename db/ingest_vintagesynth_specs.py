#!/usr/bin/env python3
"""A vintagesynth-oldalak MUSZAKI ADATAI a sajat letoltesunkbol.

Kristof, 2026-09-03: "A vintagesynth mehet, illetve minden technikai
specifikacio is kelleni fog majd, ez az adatbazis resze lesz, ezt majd
definialom pontosan hogy hogyan szeretnem csoportositani, de kulon adatok
lesznek."

MIERT NEM LESZEDES EZ
=====================
Mert mar le van szedve. A db/batches/vintagesynth-pages-*.json 892 oldalt
tartalmaz, es abbol 877-nek VAN spec-blokkja (844 Polyphony, 769 Keyboard,
722 "Date Produced"). Egyszer sem olvastuk ki oket, mert nem volt hova tenni:
az instrument_specs tabla csak 2026-09-03-an szuletett meg (0033). Ez a
script tehat nem halozati munka, hanem egy mar meglevo fajl kiolvasasa.

Ugyanez a lecke jott elo aznap a Korg KR-55-nel: Kristof atadott egy
vintagesynth-linket, es az adatlap MAR OTT ALLT a sajat batch-unkben.

A PAROSITAS ket uton megy, ebben a sorrendben:
  1. slug: az instruments.source_url-ben ott all a "/<gyarto>/<modell>" resz,
     ez pontos egyezes.
  2. gyarto + normalizalt nev: a lap display_name-jebol levagjuk a gyarto
     nevet, es a maradekot vetjuk ossze a hangszer nevevel.
Ami egyiken sem megy at, az NEM keletkezik uj sorkent. Uj hangszert ez a
script szandekosan nem hoz letre: a nev-parositas hibaja igy legfeljebb egy
kimaradt adat, nem egy kitalalt gep.

EVSZAM: a "Date Produced" mezo elso negyjegyu szama a gyartas KEZDETE
("1979 - mid-eighties" -> 1979). Ezt csak akkor irjuk be, ha nalunk MEG NINCS
evszam, es a jegyzetbe bekerul a teljes eredeti szoveg is, mert a "1979 -
mid-eighties" tobbet mond, mint a puszta 1979.

Hasznalat:
  python3 db/ingest_vintagesynth_specs.py            # szamol, nem ir
  python3 db/ingest_vintagesynth_specs.py --apply
"""

import argparse
import glob
import json
import re
import sqlite3
from pathlib import Path

from maker_lookup import MakerLookup, norm

HERE = Path(__file__).resolve().parent
DB = HERE / "synthsworld.sqlite"
BATCHES = str(HERE / "batches" / "vintagesynth-pages*.json")
SOURCE = "vintagesynth"
DOMAIN = "vintagesynth.com"
YEAR = re.compile(r"\b(18\d\d|19\d\d|20[0-2]\d)\b")


def pages():
    out = []
    for f in sorted(glob.glob(BATCHES)):
        stack = [json.load(open(f, encoding="utf-8"))]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get("model_slug") and o.get("specs"):
                    out.append(o)
                stack += list(o.values())
            elif isinstance(o, list):
                stack += o
    return out


def slug_of(url):
    """A vintagesynth-cimbol a "<gyarto>/<modell>" resz, index.php nelkul."""
    if not url or DOMAIN not in url:
        return None
    tail = url.split(DOMAIN, 1)[1].strip("/")
    tail = tail.replace("index.php/", "")
    parts = [p for p in tail.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    makers = MakerLookup(con)

    by_slug, by_maker_name = {}, {}
    for r in con.execute(
            "SELECT id, name, year, manufacturer_id, source_url FROM instruments"):
        s = slug_of(r["source_url"])
        if s:
            by_slug.setdefault(s, r["id"])
        by_maker_name.setdefault((r["manufacturer_id"], norm(r["name"])), r["id"])

    rows = pages()
    print(f"spec-blokkos oldal a batch-ekben: {len(rows)}")

    matched, unmatched, spec_n, year_n, link_n = 0, [], 0, 0, 0
    for p in rows:
        slug = f'{p.get("maker_slug")}/{p.get("model_slug")}'
        iid = by_slug.get(slug)
        if iid is None:
            mid = makers.find((p.get("maker_slug") or "").replace("-", " "))
            name = p.get("display_name") or ""
            if mid:
                canon = makers.canon_by_id.get(mid, "")
                short = re.sub(rf"^{re.escape(canon)}\s+", "", name, flags=re.I)
                iid = (by_maker_name.get((mid, norm(short)))
                       or by_maker_name.get((mid, norm(name))))
        if iid is None:
            unmatched.append(p.get("display_name") or slug)
            continue
        matched += 1
        if not args.apply:
            spec_n += len(p["specs"])
            continue
        for label, value in p["specs"].items():
            if not value:
                continue
            key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            cur = con.execute(
                """INSERT OR IGNORE INTO instrument_specs
                   (instrument_id, field, label, value, source_url, source_name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (iid, key, label, str(value)[:2000], p["source_url"], SOURCE))
            spec_n += cur.rowcount
        made = p["specs"].get("Date Produced") or ""
        m = YEAR.search(made)
        if m:
            row = con.execute("SELECT year FROM instruments WHERE id=?", (iid,)).fetchone()
            if row["year"] is None:
                con.execute(
                    "UPDATE instruments SET year=?, review_note=COALESCE(review_note,'')||? "
                    "WHERE id=?",
                    (int(m.group(1)),
                     f' [vintagesynth spec 2026-09-03] Evszam a "Date Produced: {made}" '
                     f'mezobol, a gyartas kezdete. Forras: {p["source_url"]}', iid))
                year_n += 1
        if not con.execute("SELECT 1 FROM external_links WHERE instrument_id=? AND url=?",
                           (iid, p["source_url"])).fetchone():
            con.execute(
                """INSERT INTO external_links (manufacturer_id, instrument_id, url, domain,
                                               label, link_type, found_on, source_name)
                   SELECT manufacturer_id, ?, ?, ?, ?, 'spec', ?, ? FROM instruments WHERE id=?""",
                (iid, p["source_url"], DOMAIN,
                 f'{p.get("display_name")} -- adatlap', BATCHES, SOURCE, iid))
            link_n += 1

    print(f"parositva: {matched}, nem parositott: {len(unmatched)}")
    print(f"spec-ertek: {spec_n}, potolt evszam: {year_n}, uj link: {link_n}")
    if unmatched:
        # A nem parositott lapok tobbsege NEM hiba: olyan gyarto, aki meg nincs
        # a tablankban (Vermona, Technosaurus, Wiard, Welson). Ez tehat
        # kutatasi jelolt-lista, ezert kiirjuk fajlba is.
        out = HERE / "leads" / "vintagesynth-nem-parositott.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text("# vintagesynth-oldalak, amikhez nincs sorunk\n\n"
                       "Generalva: db/ingest_vintagesynth_specs.py. Tobbsegukben nem hiba,\n"
                       "hanem olyan gyarto, aki meg nincs a tablankban.\n\n"
                       + "".join(f"- {u}\n" for u in sorted(unmatched)))
        print(f"\nnem parositott lista: {out}")
        for u in unmatched[:15]:
            print("  ", u)
    if args.apply:
        con.execute("UPDATE source_domains SET harvester='ingest_vintagesynth_specs', "
                    "harvested_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=?", (DOMAIN,))
        con.commit()
        print("\nirva.")
    else:
        print("\nSZARAZ futas. Iras: --apply")


if __name__ == "__main__":
    main()
