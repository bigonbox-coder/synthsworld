#!/usr/bin/env python3
"""Harvest instrument MODEL NAMES from English Wikipedia category trees.

Phase-2 groundwork: names only, no specifications. Wikipedia's
"Category:<Maker> synthesizers" tree (plus the drum-machine / sampler /
workstation / sequencer categories) is a free, dense, already-curated list of
notable models, so this runs as a script instead of costing fetch tokens.

Writes an ingest.py-compatible batch to stdout (or --out FILE); it never
touches the database itself, and every entry carries the Wikipedia URL it came
from, so nothing lands source-free.

Unmatched titles are PRINTED to stderr, never silently dropped -- that list is
where new manufacturers get spotted.

Usage:  python3 db/harvest_wikipedia_instruments.py --out db/batches/x.json
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "Synthsworld/1.0 (https://github.com/bigonbox-coder/synthsworld)"}

# Categories whose members are instruments in scope. Amplifiers and effects
# stay out, same scope rule as the manufacturer list.
FLAT_CATEGORIES = [
    ("Category:Drum machines", "drum machine"),
    ("Category:Samplers (musical instrument)", "sampler"),
    ("Category:Music workstations", "music workstation"),
    ("Category:Music sequencers", "sequencer"),
    ("Category:Electronic organs", "electronic organ"),
    ("Category:Electric pianos", "electric piano"),
    ("Category:Groove machines", "groove machine"),
]
BY_MAKER_ROOT = "Category:Synthesizers by manufacturer"

# Category / title tokens -> canonical_name in our DB. Only needed where the
# short form does not literally prefix the stored name.
ALIASES = {
    "arp": "ARP Instruments",
    "ems": "Electronic Music Studios (London) Ltd.",
    "e-mu": "E-mu Systems",
    "emu": "E-mu Systems",
    "korg": "Korg Inc.",
    "roland": "Roland Corporation",
    "moog": "Moog Music",
    "akai": "Akai Professional",
    "kurzweil": "Kurzweil Music Systems",
    "buchla": "Buchla Electronic Musical Instruments",
    "sequential circuits": "Sequential",
    "ppg": "Palm Products GmbH",
    "palm products": "Palm Products GmbH",
    "kawai": "Kawai Musical Instruments",
    "waldorf": "Waldorf Music",
    "oxford synthesiser": "Oxford Synthesiser Company",
    "edp": "Electronic Dream Plant",
    "new england digital": "New England Digital",
    "serge": "Serge Modular Music Systems",
    "gem": "GEM (General Electro Music)",
    "hammond": "Hammond Organ Company",
    "formanta": "Formanta Radio Factory",
}

# Models whose title carries no maker prefix at all.
EXTRA_TITLE_MAP = {
    "Synclavier": "New England Digital",
    "ASR-10": "Ensoniq",
    "Prophet 2000": "Sequential",
    "Kaoss Pad": "Korg Inc.",
    "Volca Beats": "Korg Inc.",
    "Drumtraks": "Sequential",
}

# Titles that are concepts, people, companies or software, not instruments.
REJECT_EXACT = {
    "Drum machine", "Electronic drum", "Sampler (musical instrument)",
    "Music workstation", "Music sequencer", "Synthesizer", "Electronic organ",
    "Electric piano", "Groove machine", "MUSIC-N", "Roger Linn",
    "List of synthesizer manufacturers",
}
REJECT_RE = re.compile(r"\((software|company|musician|band|programming language)\)$", re.I)


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("action", "query")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    data = json.load(urllib.request.urlopen(req, timeout=60))
    if "error" in data:  # never let an API error look like an empty category
        raise RuntimeError(data["error"])
    return data


def members(cat, cmtype="page"):
    out, cont = [], {}
    while True:
        d = api(list="categorymembers", cmtitle=cat, cmlimit=500, cmtype=cmtype, **cont)
        out += d["query"]["categorymembers"]
        if "continue" not in d:
            return out
        cont = d["continue"]


def load_makers(conn):
    """canonical_name plus every historical name, lowercased, longest first."""
    index = {}
    for cid, name in conn.execute("SELECT id, canonical_name FROM manufacturers"):
        index[name.lower()] = name
    for name, canon in ALIASES.items():
        row = conn.execute(
            "SELECT canonical_name FROM manufacturers WHERE canonical_name = ?", (canon,)
        ).fetchone()
        if row:
            index[name] = row[0]
    try:
        for canon, hist in conn.execute(
            """SELECT m.canonical_name, h.name FROM manufacturer_name_history h
               JOIN manufacturers m ON m.id = h.manufacturer_id"""
        ):
            index.setdefault(hist.lower(), canon)
    except sqlite3.OperationalError:
        pass
    return index


def strip_maker_prefix(name, maker, index):
    """'Roland Jupiter-8' -> 'Jupiter-8'; the parent record already says Roland.

    Only strips when what remains still reads as a model name, so
    'Moog synthesizer' and 'Moog modular synthesizer' survive intact.
    """
    keys = sorted((k for k, v in index.items() if v == maker), key=len, reverse=True)
    for key in keys:
        if name.lower().startswith(key + " "):
            rest = name[len(key) + 1:].strip()
            if len(rest) >= 2 and (rest[0].isupper() or rest[0].isdigit()):
                return rest
            return name
    return name


def match_maker(text, index):
    low = text.lower()
    for key in sorted(index, key=len, reverse=True):
        if low.startswith(key + " ") or low == key:
            return index[key]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    index = load_makers(conn)

    found = {}       # canonical_name -> {model name -> entry}
    unmatched = []

    def add(maker, title, category):
        if title in REJECT_EXACT or REJECT_RE.search(title):
            return
        if title.lower() in index:          # the manufacturer's own article
            return
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        name = strip_maker_prefix(title, maker, index)
        entry = {"name": name, "category": category, "source_url": url}
        found.setdefault(maker, {}).setdefault(name, entry)

    # 1. per-manufacturer synthesizer categories
    for sub in members(BY_MAKER_ROOT, cmtype="subcat"):
        cat = sub["title"]
        short = cat[len("Category:"):].replace(" synthesizers", "")
        maker = match_maker(short, index)
        if not maker:
            unmatched.append(f"[category] {cat}")
            continue
        for page in members(cat):
            # NO category here. "Category:Roland synthesizers" is a container
            # for that maker's instruments, and Wikipedia files drum machines,
            # samplers and controllers in it too -- the CR-78 and the Boss
            # SP-303 both arrived through this pass. Stamping 'synthesizer' on
            # every member turned a guess into a stored fact. The flat
            # categories below are real evidence; this one is not.
            add(maker, page["title"], None)

    # 2. flat instrument categories, matched by title prefix
    for cat, category in FLAT_CATEGORIES:
        try:
            pages = members(cat)
        except Exception as exc:
            print(f"skip {cat}: {exc}", file=sys.stderr)
            continue
        for page in pages:
            title = page["title"]
            if title in REJECT_EXACT or REJECT_RE.search(title):
                continue
            maker = EXTRA_TITLE_MAP.get(title) or match_maker(title, index)
            if maker:
                add(maker, title, category)
            else:
                unmatched.append(f"[{category}] {title}")

    batch = {"manufacturers": [
        {"canonical_name": maker, "instruments": sorted(items.values(), key=lambda e: e["name"])}
        for maker, items in sorted(found.items())
    ]}

    text = json.dumps(batch, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        total = sum(len(m["instruments"]) for m in batch["manufacturers"])
        print(f"{total} instruments across {len(batch['manufacturers'])} manufacturers -> {args.out}")
    else:
        print(text)

    if unmatched:
        print(f"\n-- {len(unmatched)} unmatched (candidate new manufacturers / out of scope):",
              file=sys.stderr)
        for u in sorted(unmatched):
            print("   " + u, file=sys.stderr)


if __name__ == "__main__":
    main()
