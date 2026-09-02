#!/usr/bin/env python3
"""Az admin fooldal allitasainak ellenorzese: igazat mond-e meg.

Kristof, 2026-09-02: "Ne feledd az admin up to date legyen!"

MIERT KELL EZ
=============
Az admin nem kulon adat, hanem a tabla tukre -- de csak azokat a mezoket
tudja mutatni, amiket a munka vegen tenyleg kitoltunk. Ket ilyen mulasztas
volt ugyanazon a napon:

  - a synth-db.com leszedoje elkeszult es le is futott, de a
    source_domains.harvester ures maradt, ezert a fooldal tovabbra is
    munkakent hirdette;
  - a mar leszedett forrasok termekoldalai (9052 darab) tovabbra is
    jovobeli hozamkent szerepeltek az elorejelzesben.

Egyik sem latszik a kodbol es egyik sem hibauzenet. Ezert kell egy futtathato
ellenorzes, amit a napi kor a commit ELOTT lefuttat.

MIT NEZ MEG
===========
Csak olyat, ami a fooldalon LATSZIK, es amirol a tabla maga meg tudja
mondani, hogy elavult. Nem stilus-ellenorzes es nem lint.

Kimenet: emberi lista. Visszateresi ertek 1, ha van elavult allitas.

Hasznalat:
    python3 db/admin_freshness_check.py
    python3 db/admin_freshness_check.py --db /masik.sqlite
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "synthsworld.sqlite"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    stale, info = [], []

    # 1. Van adatunk a domainrol, de a leszedo mezo ures -> a fooldal munkakent
    #    mutatja azt, ami kesz. Ez tortent a synth-db.com-mal.
    for r in con.execute(
        """SELECT d.domain,
                  (SELECT COUNT(*) FROM instruments i
                    WHERE i.source_url LIKE '%' || d.domain || '%') AS insts,
                  (SELECT COUNT(*) FROM external_links l
                    WHERE l.domain = d.domain) AS links
             FROM source_domains d
            WHERE d.harvester IS NULL AND d.verdict='harvestable'"""):
        # A fooldal CSAK a harvestable verdictuket sorolja munkakent, tehat csak
        # azok lehetnek elavultak. Egy-ket kulso link nem bizonyit leszedest:
        # bizonyitek a tolunk szarmazo hangszer, vagy sok link ugyanarrol.
        if r["insts"] or r["links"] >= 20:
            stale.append(f"{r['domain']}: mar hoztunk belole adatot "
                         f"({r['insts']} hangszer, {r['links']} link), de a "
                         f"source_domains.harvester URES -- a fooldal leszedendokent mutatja")

    # 2. Van leszedo es van adat, de a harvested_at ures -> az elorejelzes a
    #    mar feldolgozott oldalakat is jovobeli hozamkent szamolja.
    for r in con.execute(
        """SELECT d.domain, d.product_urls,
                  (SELECT COUNT(*) FROM instruments i
                    WHERE i.source_url LIKE '%' || d.domain || '%') AS insts
             FROM source_domains d
            WHERE d.harvester IS NOT NULL AND d.harvested_at IS NULL"""):
        if r["insts"]:
            stale.append(f"{r['domain']}: {r['insts']} hangszer szarmazik innen, de a "
                         f"harvested_at URES -- a {r['product_urls'] or 0} termekoldal "
                         f"tovabbra is jovobeli hozamkent latszik")

    # 3. A backlogban pending sor, aminek az elofeltetele mar KESZ. Ilyenkor a
    #    munka indithato, csak senki nem tud rola.
    for r in con.execute(
        "SELECT job_name, prerequisite FROM processing_backlog WHERE status='pending'"):
        if (r["prerequisite"] or "").strip().upper().startswith("KESZ"):
            info.append(f"processing_backlog: '{r['job_name']}' pending, de az elofeltetele KESZ "
                        f"-- indithato (ha tokenkoltseg, Kristof donti el)")

    # 4. Olyan forras-domain, ami egyaltalan nincs a source_domains-ben. Ilyenkor
    #    a fooldal forras-listaja nem teljes.
    known = {r["domain"] for r in con.execute("SELECT domain FROM source_domains")}
    seen = {}
    for r in con.execute("SELECT source_url FROM instruments WHERE source_url IS NOT NULL"):
        u = r["source_url"]
        host = u.split("//", 1)[-1].split("/", 1)[0].lower()
        seen[host] = seen.get(host, 0) + 1
    # A wiki-csalad es a wikidata nem leszedendo forras, hanem hivatkozas: azok
    # hianya a source_domains-bol nem hiba. Kevesbe hasznalt hostot sem soroljuk,
    # kulonben a lista minden nap zajos lesz.
    REFERENCE = ("wikipedia.org", "wikidata.org", "fandom.com", "wikimedia.org")
    for host, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        if n < 20 or host.endswith(REFERENCE):
            continue
        if not any(host == d or host.endswith("." + d) or d.endswith("." + host) for d in known):
            info.append(f"{host}: {n} hangszer forrasa, de nincs a source_domains-ben "
                        f"-- a forras-lista nem teljes")

    # 5. Varolistas nev, ami PONTOSAN egyezik egy meglevo gyartoval: a
    #    duplikatum-szuro nem futott le a legutobbi beemeles ota.
    # A csonk (unresearched) gyartokhoz tartozo sorok SZANDEKOSAN maradnak a
    # sorban: eppen azok inditanak kutatast a csonkra. A queue_dupe_check.py is
    # bekene hagyja oket, tehat itt sem szabad hibakent jelenteni -- kulonben az
    # ellenorzes minden nap ugyanazt a nem-hibat kiabalja.
    dupes = con.execute(
        """SELECT COUNT(*) FROM discovery_queue q
            WHERE q.status='found'
              AND EXISTS (SELECT 1 FROM manufacturers m
                           WHERE lower(m.canonical_name) = lower(q.manufacturer_name)
                             AND m.confidence_level <> 'unresearched')"""
    ).fetchone()[0]
    if dupes:
        stale.append(f"{dupes} varolistas nev PONTOSAN egyezik egy meglevo gyartoval "
                     f"-- fusson: python3 db/queue_dupe_check.py --apply")

    n_review = con.execute(
        "SELECT COUNT(*) FROM instruments WHERE review_status='needs_review'").fetchone()[0]
    if n_review:
        info.append(f"{n_review} hangszer var emberi dontesre (halott forras) -- a fooldali "
                    f"'Hangszer: forrás?' csempe ezt mutatja")

    for line in stale:
        print(f"ELAVULT  {line}")
    for line in info:
        print(f"info     {line}")
    if not stale:
        print("Az admin allitasai naprakeszek.")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
