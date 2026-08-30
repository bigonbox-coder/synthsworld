#!/usr/bin/env python3
"""Harvest the synthxl.com service-manual archive into external_links.

Source: https://www.synthxl.com/service-manual/ -- an index of ~67 gear
makers, each with a page listing one sub-page per model. Kristof supplied it
2026-08-30, right after synfo.nl. The two overlap but neither contains the
other: synfo is one flat page of direct PDF links, synthxl is a page per
model.

Same principle as harvest_synfo.py, and the same restraint: we store the link
to the model's page, never the PDF itself. Copyright on third-party scans of
service documentation is not ours to assume.

Scope note. synthxl indexes pro audio as well as instruments -- AKG, Shure,
Klark Teknik, Crest, Electro-Voice, Ramsa, Tascam, Fostex. Those are
microphones, PA and recorders, not instruments, and this script does not queue
them as manufacturer candidates. It still ingests their links if a matching
manufacturer record somehow exists, because that is the operator's call, not
the script's.

Usage:
  python3 db/harvest_synthxl.py --fetch        # index + every maker page
  python3 db/harvest_synthxl.py --dry-run
  python3 db/harvest_synthxl.py --ingest
  python3 db/harvest_synthxl.py --candidates   # makers we hold no record for
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

ROOT = Path(__file__).resolve().parent
DB = ROOT / "synthsworld.sqlite"
CACHE = ROOT / "cache" / "synthxl"
INDEX = "https://www.synthxl.com/service-manual/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")

# maker slug -> canonical_name, where the slug is not the company name
SLUG_ALIASES = {
    "arp": "ARP Instruments",
    "akai": "Akai Professional",
    "e-mu-system": "E-mu Systems",
    "edp": "Electronic Dream Plant",
    "electronic-music-studios": "Electronic Music Studios (London) Ltd.",
    "general-music": "Generalmusic",
    "hammond": "Hammond Organ Company",
    "kawai": "Kawai Musical Instruments",
    "korg": "Korg Inc.",
    "kurzweil": "Kurzweil Music Systems",
    "moog": "Moog Music",
    "roland": "Roland Corporation",
    "boss": "Roland Corporation",
    "edirol": "Roland Corporation",
    "sequential-circuit": "Sequential",
    "waldorf": "Waldorf Music",
    "buchla": "Buchla Electronic Musical Instruments",
    "electronic-music-laboratories": "EML (Electronic Music Laboratories)",
}

# Not instrument makers -- indexed by synthxl but out of this museum's scope.
NOT_INSTRUMENTS = {
    "akg-service-manual", "shure", "klark-teknik", "crest", "electro-voice", "ramsa",
    "tascam", "fostex", "alto", "peavey", "pioneer", "zoom", "various-brand",
}

LINK_TYPE = "service_mod"
SOURCE_NAME = "synthxl"


def now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def get(url, dest):
    subprocess.run(["curl", "-sSL", "--max-time", "30", "--compressed",
                    "-A", UA, url, "-o", str(dest)], check=True)


def maker_slugs():
    html = (CACHE / "index.html").read_text(encoding="utf-8", errors="replace")
    slugs = re.findall(r'href="https://www\.synthxl\.com/service-manual/([^"/]+)/?"', html)
    return sorted(set(slugs))


def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    get(INDEX, CACHE / "index.html")
    slugs = maker_slugs()
    print(f"{len(slugs)} makers on the index")
    for i, s in enumerate(slugs, 1):
        dest = CACHE / f"{s}.html"
        if dest.exists():
            continue
        get(f"https://www.synthxl.com/service-manual/{s}/", dest)
        print(f"  [{i}/{len(slugs)}] {s}")
        time.sleep(0.5)          # be a polite guest on a hobbyist's server


# A slug that shows up on many different maker pages is site chrome (a nav
# item, a blog post), not a model. Six was chosen because no real model page is
# linked from six different makers' pages, while every chrome link is.
_CHROME = None


def _chrome():
    """Slugs linked from >=6 maker pages: site furniture, not models."""
    global _CHROME
    if _CHROME is None:
        from collections import Counter
        seen = Counter()
        for s in maker_slugs():
            for path in _paths(s):
                seen[path] += 1
        _CHROME = {p for p, n in seen.items() if n >= 6}
    return _CHROME


def _paths(slug):
    f = CACHE / f"{slug}.html"
    if not f.exists():
        return []
    html = f.read_text(encoding="utf-8", errors="replace")
    skip = re.compile(r"^(service-manual|owner-manual-archive|datasheet|blog|cookie|"
                      r"join-in|all-listing|all-listings|gear-makers|a-great-thanks-to|"
                      r"comments|feed|wp-|category|tag|author|page)", re.I)
    out, seen = [], set()
    for path in re.findall(r'href="https://www\.synthxl\.com/([^"?#]+?)/?"', html):
        if "/" in path or not path or skip.match(path) or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def models_for(slug):
    """-> list of (model_name, url) from one maker page."""
    out = []
    for path in _paths(slug):
        if path in _chrome():
            continue
        name = path
        # drop a leading maker token: moog-minimoog -> minimoog
        head = slug.split("-")[0]
        if name.startswith(head + "-"):
            name = name[len(head) + 1:]
        name = name.replace("-", " ").strip()
        out.append((name, f"https://www.synthxl.com/{path}/"))
    return out


def resolve(conn, slugs):
    makers = {r[0]: r[1] for r in conn.execute("select canonical_name, id from manufacturers")}
    by_norm = {norm(k): v for k, v in makers.items()}
    alt = {}
    for name, mid in conn.execute("select name, manufacturer_id from manufacturer_name_history"):
        alt.setdefault(norm(name), mid)
    mapping, missing = {}, []
    for s in slugs:
        want = SLUG_ALIASES.get(s, s.replace("-", " "))
        mid = makers.get(want) or by_norm.get(norm(want)) or alt.get(norm(want))
        if mid is None:
            hits = [v for k, v in by_norm.items() if len(norm(want)) > 3 and k.startswith(norm(want))]
            mid = hits[0] if len(hits) == 1 else None
        (mapping.__setitem__(s, mid) if mid else missing.append(s))
    return mapping, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--candidates", action="store_true")
    args = ap.parse_args()

    if args.fetch:
        fetch()
        if not (args.dry_run or args.ingest or args.candidates):
            return
    if not (CACHE / "index.html").exists():
        sys.exit(f"nothing cached in {CACHE} -- run with --fetch first")

    slugs = maker_slugs()
    conn = sqlite3.connect(DB)
    mapping, missing = resolve(conn, slugs)

    if args.candidates:
        interesting = [s for s in missing if s not in NOT_INSTRUMENTS]
        print(f"{len(missing)} makers with no record; {len(interesting)} of them plausibly instruments:")
        for s in interesting:
            print(f"  {s}  ({len(models_for(s))} models)")
        print(f"\nskipped as out of scope: {', '.join(sorted(set(missing) & NOT_INSTRUMENTS))}")
        return

    planned, unmatched = [], []
    for s in slugs:
        mid = mapping.get(s)
        if mid is None:
            continue
        idx = {norm(r[0]): r[1] for r in conn.execute(
            "select name, id from instruments where manufacturer_id=?", (mid,))}
        for name, url in models_for(s):
            iid = idx.get(norm(name))
            if iid is None:
                unmatched.append((s, name))
            planned.append((mid, iid, name, url, s))

    attached = sum(1 for p in planned if p[1])
    print(f"{len(slugs)} makers, {len(mapping)} resolved, {len(planned)} model links, "
          f"{attached} matched to an instrument, {len(planned) - attached} to the manufacturer")
    if missing:
        print(f"unresolved makers ({len(missing)}): {', '.join(missing)}")

    if args.dry_run:
        for mid, iid, name, url, s in planned[:20]:
            print(f"  m={mid:<4} i={str(iid or '-'):<6} {name[:40]:<42} {url}")
        print(f"  ... {len(set(unmatched))} model names have no instrument row")
        return

    if not args.ingest:
        print("nothing written -- pass --ingest to write, --dry-run to preview")
        return

    ts = now_iso()
    have = {r[0] for r in conn.execute(
        "select url from external_links where source_name=?", (SOURCE_NAME,))}
    n = 0
    for mid, iid, name, url, s in planned:
        if url in have:
            continue
        conn.execute(
            "insert into external_links (manufacturer_id, instrument_id, url, domain, "
            "label, link_type, found_on, source_name, status, created_at) "
            "values (?,?,?,?,?,?,?,?,?,?)",
            (None if iid else mid, iid, url, "synthxl.com",
             f"{name} service manual", LINK_TYPE,
             f"https://www.synthxl.com/service-manual/{s}/", SOURCE_NAME, "unchecked", ts))
        n += 1
    conn.commit()
    print(f"inserted {n} links (source_name={SOURCE_NAME})")


if __name__ == "__main__":
    main()
