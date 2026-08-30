#!/usr/bin/env python3
"""Harvest instrument model names from NON-ENGLISH Wikipedia category trees.

English Wikipedia barely covers the vintage European, Soviet and Japanese
makers -- the Italian wiki knows Crumar DS-2 and Logan String Melody, the
Russian one knows Polivoks and Aelita, and none of them show up in
`Category:Synthesizers by manufacturer`. This script walks the same category
idea in other languages.

Local wikis title articles in the local script and the local naming habit, so
every candidate is resolved to its Wikidata QID and then to the ENGLISH label
before it is written -- otherwise the same instrument lands twice, once as
"Поливокс" and once as "Polivoks". Same mechanic as seed_from_wikipedia.py.

Root categories are found through the langlinks of the English ones, so no
per-language category name has to be hardcoded.

Usage:  python3 db/harvest_wikipedia_instruments_ml.py --langs it,de,ru,ja,fr,es,nl,pl \
            --out db/batches/x.json
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_wikipedia_instruments import (  # noqa: E402
    ALIASES, EXTRA_TITLE_MAP, REJECT_EXACT, REJECT_RE, load_makers, match_maker,
    strip_maker_prefix,
)

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = {"User-Agent": "Synthsworld/1.0 (https://github.com/bigonbox-coder/synthsworld)"}

ROOT_CATEGORIES = {
    "Category:Synthesizers": "synthesizer",
    "Category:Synthesizers by manufacturer": "synthesizer",
    "Category:Drum machines": "drum machine",
    "Category:Samplers (musical instrument)": "sampler",
    "Category:Electronic organs": "electronic organ",
}


def wapi(host, **params):
    params.setdefault("format", "json")
    params.setdefault("action", "query")
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    data = json.load(urllib.request.urlopen(req, timeout=60))
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def langlinks(title, langs):
    d = wapi("en.wikipedia.org", prop="langlinks", titles=title, lllimit=500)
    page = next(iter(d["query"]["pages"].values()))
    return {ll["lang"]: ll["*"] for ll in page.get("langlinks", []) if ll["lang"] in langs}


def members(host, cat, cmtype="page"):
    out, cont = [], {}
    while True:
        d = wapi(host, list="categorymembers", cmtitle=cat, cmlimit=500, cmtype=cmtype, **cont)
        out += d["query"]["categorymembers"]
        if "continue" not in d:
            return out
        cont = d["continue"]


def qids(host, titles):
    """local title -> wikidata QID (pageprops), in batches of 50."""
    found = {}
    titles = list(titles)
    for i in range(0, len(titles), 50):
        d = wapi(host, prop="pageprops", titles="|".join(titles[i:i + 50]), ppprop="wikibase_item")
        for page in d["query"]["pages"].values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                found[page["title"]] = qid
    return found


def english_labels(qid_list):
    """QID -> (english label, set of P31 QIDs), in batches of 50."""
    out = {}
    qid_list = list(qid_list)
    for i in range(0, len(qid_list), 50):
        chunk = qid_list[i:i + 50]
        url = ("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "labels|claims", "languages": "en", "format": "json"}))
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))
        for qid, ent in (d.get("entities") or {}).items():
            label = (ent.get("labels", {}).get("en") or {}).get("value")
            p31 = {c["mainsnak"]["datavalue"]["value"]["id"]
                   for c in ent.get("claims", {}).get("P31", [])
                   if c["mainsnak"].get("datavalue")}
            out[qid] = (label, p31)
    return out


# instance-of classes that are definitely NOT an instrument model
REJECT_P31 = {
    "Q5",          # human
    "Q4830453",    # business
    "Q783794",     # company
    "Q7397",       # software
    "Q341",        # free software
    "Q11424",      # film
    "Q482994",     # album
    "Q134556",     # single
    "Q7889",       # video game
    "Q4167410",    # disambiguation page
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="it,de,ru,ja,fr,es,nl,pl")
    ap.add_argument("--out")
    args = ap.parse_args()
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    conn = sqlite3.connect(DB_PATH)
    index = load_makers(conn)

    found, unmatched, rejected = {}, [], []

    for root, category in ROOT_CATEGORIES.items():
        try:
            local = langlinks(root, langs)
        except Exception as exc:
            print(f"langlinks {root}: {exc}", file=sys.stderr)
            continue
        for lang, cat in local.items():
            host = f"{lang}.wikipedia.org"
            try:
                pages = [m["title"] for m in members(host, cat)]
                for sub in members(host, cat, cmtype="subcat"):
                    pages += [m["title"] for m in members(host, sub["title"])]
            except Exception as exc:
                print(f"{host} {cat}: {exc}", file=sys.stderr)
                continue
            if not pages:
                continue

            qmap = qids(host, pages)
            labels = english_labels(set(qmap.values()))

            for title in pages:
                qid = qmap.get(title)
                label, p31 = labels.get(qid, (None, set()))
                name = label or title
                if p31 & REJECT_P31:
                    rejected.append(f"[{lang}] {title} -> {name} (P31)")
                    continue
                if name in REJECT_EXACT or REJECT_RE.search(name):
                    continue
                if name.lower() in index:          # a manufacturer's own article
                    continue
                maker = EXTRA_TITLE_MAP.get(name) or match_maker(name, index)
                if not maker:
                    unmatched.append(f"[{lang}] {name}")
                    continue
                url = f"https://{host}/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
                display = strip_maker_prefix(name, maker, index)
                found.setdefault(maker, {}).setdefault(
                    display, {"name": display, "category": category, "source_url": url})

    batch = {"manufacturers": [
        {"canonical_name": maker, "instruments": sorted(items.values(), key=lambda e: e["name"])}
        for maker, items in sorted(found.items())]}
    text = json.dumps(batch, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        total = sum(len(m["instruments"]) for m in batch["manufacturers"])
        print(f"{total} instruments across {len(batch['manufacturers'])} manufacturers -> {args.out}")
    else:
        print(text)

    for header, rows in (("rejected by P31", rejected), ("unmatched", unmatched)):
        if rows:
            print(f"\n-- {len(rows)} {header}:", file=sys.stderr)
            for r in sorted(set(rows)):
                print("   " + r, file=sys.stderr)


if __name__ == "__main__":
    main()
