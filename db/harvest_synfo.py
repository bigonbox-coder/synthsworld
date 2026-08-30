#!/usr/bin/env python3
"""Harvest the synfo.nl service-manual index into external_links.

Source: https://www.synfo.nl/pages/servicemanuals.html -- one flat page of
~680 links to service manuals, schematics and build instructions, filed in
per-manufacturer folders. Kristof supplied it 2026-08-30.

Why a script and not a research pass: the page carries no prose worth
reading. Every fact is in the URL -- the folder is the manufacturer and the
filename is the model plus a document type. So this is pure rule work, and
rule work should not cost agent fetches.

What it does NOT do: download the PDFs. They are third-party scans of
manufacturers' service documentation and their copyright status is not ours
to assume. We store the link, not the file. If Kristof later wants the files
mirrored, that is a separate decision with a separate answer.

Attachment rule, same spirit as ingest_links.py: a manual belongs to the
INSTRUMENT when its model can be matched to one we already hold, otherwise to
the MANUFACTURER. A manual for a model we have never heard of is still worth
keeping -- it is evidence the model exists, and phase 2 can pick it up.

Usage:
  python3 db/harvest_synfo.py --fetch          # pull the page to db/cache/
  python3 db/harvest_synfo.py --dry-run        # show what would be written
  python3 db/harvest_synfo.py --ingest         # write to external_links
  python3 db/harvest_synfo.py --unmatched      # models we hold no instrument for
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "synthsworld.sqlite"
CACHE = ROOT / "cache" / "synfo-servicemanuals.html"
PAGE = "https://www.synfo.nl/pages/servicemanuals.html"
BASE = "https://www.synfo.nl/servicemanuals/"

# Folder name on synfo -> canonical_name in manufacturers. Only the ones where
# the folder is not simply the company name. Anything unmapped falls back to a
# normalised-name lookup, and failing that the link is skipped and reported.
FOLDER_ALIASES = {
    "Arp": "ARP Instruments",
    "Emu": "E-mu Systems",
    "BigBriar": "Big Briar",
    "GEM": "Generalmusic",
    "Linne": "Linn",
    "MPC": "Akai Professional",
    "Boss": "Roland",          # Boss is Roland's brand, not a separate company
    "Solina": "Eminent",
    "EDP": "Electronic Dream Plant",
    "EMS": "Electronic Music Studios (London) Ltd.",
}

# Trailing tokens that describe the document, not the model.
DOC_TOKENS = [
    "SERVICE_MANUAL", "SERVICE_NOTES", "SERVICE_INFORMATION", "SERVICE-MANUAL",
    "USER-SERVICE_MANUAL", "REPAIR_MANUAL", "OWNERS_MANUAL", "SCHEMATICS",
    "SCHEMATIC", "MIDIGUIDE", "TEST-PROGRAM", "CONSTRUCTION", "PARTS_LIST",
    "BEDIENUNGSANLEITUNG", "BAUANLEITUNG", "TUNEN-VORGANG", "ENGINEERING-CHANGE",
    "DEVELOPEMENT-REPORT", "INSTALLATION", "RESOURCE_BOOK",
]

LINK_TYPE = "service_mod"
SOURCE_NAME = "synfo"


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def fetch():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sSL", "--max-time", "40", "--compressed", "-A",
         "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/126.0.0.0 Safari/537.36", PAGE, "-o", str(CACHE)],
        check=True,
    )
    print(f"fetched {CACHE} ({CACHE.stat().st_size} bytes)")


def parse():
    """-> list of {folder, filename, model, doc, url, label}"""
    html = CACHE.read_text(encoding="latin-1")
    out, seen = [], set()
    for href in re.findall(r'HREF="([^"]+)"', html, re.I):
        href = href.strip().replace("\t", "")
        m = re.search(r"servicemanuals/([^/]+)/(.+)$", href)
        if not m:
            continue
        folder, filename = m.group(1), urllib.parse.unquote(m.group(2)).strip()
        url = BASE + folder + "/" + urllib.parse.quote(filename)
        if url in seen:
            continue
        seen.add(url)

        stem = re.sub(r"\.(pdf|jpg|doc|zip|gif|png)$", "", filename, flags=re.I)
        doc = None
        for tok in sorted(DOC_TOKENS, key=len, reverse=True):
            if stem.upper().endswith("_" + tok) or stem.upper() == tok:
                doc = tok
                stem = stem[: len(stem) - len(tok)].rstrip("_-")
                break
        # a leading maker token repeats the folder; drop it
        head = stem.split("_")[0]
        if head and norm(head) and (norm(head) == norm(folder)
                                    or norm(head) in norm(FOLDER_ALIASES.get(folder, folder))
                                    or norm(FOLDER_ALIASES.get(folder, folder)).startswith(norm(head))):
            stem = stem[len(head):].lstrip("_-")
        model = stem.replace("_", " ").strip()
        out.append({
            "folder": folder, "filename": filename, "model": model,
            "doc": (doc or "DOCUMENT").replace("_", " ").title(),
            "url": url,
            "label": f"{model or folder} {(doc or 'document').replace('_', ' ').lower()}".strip(),
        })
    return out


def resolve(conn):
    """-> (folder -> manufacturer_id), unresolved folders"""
    makers = {r[0]: r[1] for r in conn.execute(
        "select canonical_name, id from manufacturers")}
    alt = {}
    for name, mid in conn.execute(
            "select name, manufacturer_id from manufacturer_name_history"):
        alt.setdefault(norm(name), mid)
    by_norm = {norm(k): v for k, v in makers.items()}

    mapping, missing = {}, []
    folders = {r["folder"] for r in parse()}
    for f in sorted(folders):
        want = FOLDER_ALIASES.get(f, f)
        mid = makers.get(want) or by_norm.get(norm(want)) or alt.get(norm(want))
        if mid is None:
            # last resort: a unique prefix match, e.g. "Kurzweil" -> "Kurzweil Music Systems"
            hits = [v for k, v in by_norm.items() if k.startswith(norm(want)) and len(norm(want)) > 3]
            mid = hits[0] if len(hits) == 1 else None
        if mid is None:
            missing.append(f)
        else:
            mapping[f] = mid
    return mapping, missing


def instrument_index(conn, mid):
    return {norm(r[0]): r[1] for r in conn.execute(
        "select name, id from instruments where manufacturer_id=?", (mid,))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--unmatched", action="store_true")
    args = ap.parse_args()

    if args.fetch:
        fetch()
        if not (args.dry_run or args.ingest or args.unmatched):
            return
    if not CACHE.exists():
        sys.exit(f"no cached page at {CACHE} -- run with --fetch first")

    rows = parse()
    conn = sqlite3.connect(DB)
    mapping, missing = resolve(conn)

    planned, unmatched = [], []
    for r in rows:
        mid = mapping.get(r["folder"])
        if mid is None:
            continue
        idx = instrument_index(conn, mid)
        iid = idx.get(norm(r["model"])) if r["model"] else None
        if iid is None and r["model"]:
            unmatched.append((r["folder"], r["model"]))
        planned.append((mid, iid, r))

    if args.unmatched:
        seen = sorted(set(unmatched))
        print(f"{len(seen)} model strings with no instrument row:")
        for folder, model in seen:
            print(f"  {folder:22} {model}")
        return

    attached = sum(1 for _, iid, _ in planned if iid)
    print(f"{len(rows)} links parsed, {len(planned)} with a known manufacturer, "
          f"{attached} matched to an instrument, {len(planned) - attached} to the manufacturer")
    if missing:
        print(f"folders with no manufacturer record ({len(missing)}): {', '.join(missing)}")

    if args.dry_run:
        for mid, iid, r in planned[:20]:
            print(f"  m={mid:<4} i={str(iid or '-'):<6} {r['label'][:60]:<62} {r['url']}")
        print("  ...")
        return

    if not args.ingest:
        print("nothing written -- pass --ingest to write, --dry-run to preview")
        return

    ts = now_iso()
    have = {r[0] for r in conn.execute(
        "select url from external_links where source_name=?", (SOURCE_NAME,))}
    n = 0
    for mid, iid, r in planned:
        if r["url"] in have:
            continue
        conn.execute(
            "insert into external_links (manufacturer_id, instrument_id, url, domain, "
            "label, link_type, found_on, source_name, status, created_at) "
            "values (?,?,?,?,?,?,?,?,?,?)",
            (None if iid else mid, iid, r["url"], "synfo.nl", r["label"],
             LINK_TYPE, PAGE, SOURCE_NAME, "unchecked", ts))
        n += 1
    conn.commit()
    print(f"inserted {n} links (source_name={SOURCE_NAME})")


if __name__ == "__main__":
    main()
