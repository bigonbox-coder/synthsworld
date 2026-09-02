#!/usr/bin/env python3
"""Re-attach manufacturer-level manual links to the instrument they name.

The manual harvesters (harvest_synfo.py, harvest_synthxl.py) decide at ingest
time whether a link belongs to an instrument or, failing a match, to the
manufacturer. That decision goes stale: every time phase 2 adds instruments,
some of those manufacturer-level links become attachable. This script re-runs
the match over links already in the table, so the answer to "where is the
manual for this machine" keeps improving without re-fetching anything.

Kristof's framing, 2026-08-30: the PDFs are not to be downloaded yet, but it
should be clear which instrument's manual sits where. That mapping is exactly
what this maintains.

Matching, in order, stopping at the first hit:
  1. the model string as written, ignoring case and punctuation
  2. with a trailing revision token dropped (MKII, II, III)
  3. each space- or slash-separated part on its own, longest first -- one file
     often covers several models (HR-16 HR-16B, CZ-101 CZ-1000, K2000 K2000R)

Rule 3 is deliberately generous about which of the covered models it lands on:
a manual for the CZ-101 and CZ-1000 together is worth having on either, and
the label keeps both names visible.

Usage:
  python3 db/relink_manuals.py --dry-run
  python3 db/relink_manuals.py --apply
  python3 db/relink_manuals.py --orphans      # model names we hold no row for
"""

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parent / "synthsworld.sqlite"
SOURCES = ("synfo", "synthxl", "bandecho")
# A bandecho 2026-09-02-en jott hozza. Nemet archivum, ezert a doku-vegzodesek
# nemetul allnak a fajlnevben (Handbuch, Schaltplan, Prospekt, Flyer), es a
# cimke maga a fajlnev, mert az anchor szovege minden linken csak "Download".

DOC_TAIL = re.compile(
    r"\s+(service manual|service notes|service information|schematics|schematic|"
    r"repair manual|owners manual|midiguide|test-program|construction|parts list|"
    r"bedienungsanleitung|bauanleitung|document|engineering-change|installation|"
    r"tunen-vorgang|developement-report|resource book|handbuch|handbuecher|schaltplan|schaltplaene|schaltbild|bedienungs-und-serviceanleitung|bedienung-und-serviceanleitung|serviceanleitung|prospekt|flyer|brochure|katalog|preisliste|garantieschein|werks-pruefprotokoll)$", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def model_of(label):
    return DOC_TAIL.sub("", label or "").strip()


def match(model, index):
    n = norm(model)
    if n in index:
        return index[n], "exact"
    trimmed = re.sub(r"(mk[iv]+|iii|ii)$", "", n)
    if trimmed != n and trimmed in index:
        return index[trimmed], "revision-trimmed"
    parts = sorted(re.split(r"[ /]+", model), key=len, reverse=True)
    for p in parts:
        if len(p) > 2 and norm(p) in index:
            return index[norm(p)], "multi-model file"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--orphans", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    index = {}
    for mid, name, iid in con.execute("select manufacturer_id, name, id from instruments"):
        index.setdefault(mid, {})[norm(name)] = iid

    rows = con.execute(
        "select id, manufacturer_id, label from external_links "
        f"where source_name in ({','.join('?' * len(SOURCES))}) "
        "and instrument_id is null and manufacturer_id is not null", SOURCES).fetchall()

    hits, orphans, how = [], [], Counter()
    for eid, mid, label in rows:
        model = model_of(label)
        if not model:
            continue
        iid, why = match(model, index.get(mid, {}))
        if iid:
            hits.append((eid, mid, iid, label, why))
            how[why] += 1
        else:
            orphans.append((mid, model))

    if args.orphans:
        names = {r[0]: r[1] for r in con.execute("select id, canonical_name from manufacturers")}
        by_maker = Counter(names.get(mid, str(mid)) for mid, _ in orphans)
        print(f"{len(orphans)} manual links name a model we hold no instrument row for.")
        print("Top makers by orphaned manuals -- these are phase-2 instrument candidates:")
        for maker, n in by_maker.most_common(20):
            print(f"  {n:5d}  {maker}")
        return

    print(f"{len(rows)} manufacturer-level manual links examined, {len(hits)} can be attached")
    for why, n in how.most_common():
        print(f"    {n:5d}  {why}")
    print(f"    {len(orphans):5d}  no instrument row (run --orphans to list by maker)")

    if args.dry_run:
        for eid, mid, iid, label, why in hits[:25]:
            print(f"  link {eid:<6} -> instrument {iid:<6} [{why}]  {label}")
        return
    if not args.apply:
        print("nothing written -- pass --apply to write, --dry-run to preview")
        return

    for eid, mid, iid, label, why in hits:
        con.execute("update external_links set instrument_id=?, manufacturer_id=null where id=?",
                    (iid, eid))
    con.commit()
    print(f"attached {len(hits)} links to instruments")


if __name__ == "__main__":
    main()
