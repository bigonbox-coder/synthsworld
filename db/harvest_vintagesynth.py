#!/usr/bin/env python3
"""Harvest model names from vintagesynth.com's sitemap.

Vintage Synth Explorer has no per-manufacturer page at all -- but its
sitemap.xml carries ~1000 URLs shaped `/index.php/<maker-slug>/<model-slug>`,
so the maker/model pairing is in the URL itself. Parsing that costs no fetch
budget and no page text is interpreted: a slug is only ever used as a name
string.

The sitemap is INCOMPLETE (the site's own /synthfinder?page=N listing is
authoritative), so treat this as a broad sweep, not a full catalogue.

Unmapped maker slugs are printed -- on this site that list is most of the
value, since it is a couple of hundred brands we have never seen.

Usage:  python3 db/harvest_vintagesynth.py --out db/batches/x.json
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_wikipedia_instruments import load_makers  # noqa: E402

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
SITEMAP = "https://www.vintagesynth.com/sitemap.xml"
UA = {"User-Agent": "Synthsworld/1.0 (https://github.com/bigonbox-coder/synthsworld)"}

# vintagesynth maker slug -> our canonical_name, where the slug does not
# simply match a name we already hold.
SLUG_ALIASES = {
    "electronic-music-studios-ems": "Electronic Music Studios (London) Ltd.",
    "ems": "Electronic Music Studios (London) Ltd.",
    "electronic-dream-plant-edp": "Electronic Dream Plant",
    "oxford-synthesiser-company": "Oxford Synthesiser Company",
    "ppg": "Palm Products GmbH",
    "e-mu": "E-mu Systems",
    "emu": "E-mu Systems",
    "korg": "Korg Inc.",
    "roland": "Roland Corporation",
    "moog": "Moog Music",
    "akai": "Akai Professional",
    "arp": "ARP Instruments",
    "kurzweil": "Kurzweil Music Systems",
    "buchla": "Buchla Electronic Musical Instruments",
    "sequential-circuits": "Sequential",
    "kawai": "Kawai Musical Instruments",
    "waldorf": "Waldorf Music",
    "serge": "Serge Modular Music Systems",
    "formanta": "Formanta Radio Factory",
    "hammond": "Hammond Organ Company",
    "teisco": "Teisco",
    "teisco-kawai": "Teisco",
    "new-england-digital": "New England Digital",
}

# not instrument pages
SKIP_SLUGS = {"node", "user", "forum", "news", "reviews", "articles", "taxonomy",
              "comment", "sites", "search", "content", "blog", "gear"}


# Words that are words, not model-code acronyms. Everything else short gets
# upper-cased, because on this site a short token is nearly always a code
# (DS, SX, KX, AX, MPC).
WORDS = {
    "one", "two", "six", "pro", "the", "and", "plus", "mini", "max", "bass",
    "rack", "series", "station", "wave", "poly", "mono", "drum", "synth",
    "synthesizer", "sequencer", "sampler", "keyboard", "organ", "piano",
    "electronic", "analog", "analogue", "digital", "studio", "module",
    "expander", "vocoder", "filter", "delay", "phaser", "controller", "touche",
    "voice", "four", "eight", "twelve", "dark", "energy", "little", "brother",
    "special", "deluxe", "orchestral", "orchestra", "performer", "spirit",
    "stratus", "gnat", "spider", "wasp", "modular", "soloist", "cruise",
    "explorer", "avatar", "odyssey", "omni", "prodigy", "liberation", "circuit",
    "micron", "fusion", "halo", "fizmo", "blofeld", "kyra", "micro", "new",
    "old", "for", "with", "system", "systems", "machine", "generator",
}


def title_case(slug):
    """Rebuild a model name from a URL slug.

    Two things matter. A slug that already carries capitals is the site's own
    spelling, so it is left alone. And a hyphen between a short alphabetic
    token and a numeric one is part of the model code (ds-2 -> DS-2), not a
    word break -- getting this wrong would store DS-2 a second time as "DS 2".
    """
    if any(c.isupper() for c in slug):
        return slug
    parts = [p for p in re.split(r"[-_]+", slug) if p]
    out = []
    for part in parts:
        if part.lower() in WORDS:
            out.append(part[:1].upper() + part[1:])
        elif re.search(r"\d", part) or len(part) <= 3:
            out.append(part.upper())
        else:
            out.append(part[:1].upper() + part[1:])
    # rejoin model codes: a short all-alpha token followed by a numeric one
    merged = [out[0]] if out else []
    for prev, cur in zip(out, out[1:]):
        if (prev.isalpha() and len(prev) <= 4 and prev.isupper()
                and re.match(r"^\d", cur)):
            merged[-1] = merged[-1] + "-" + cur
        else:
            merged.append(cur)
    return " ".join(merged)


def existing_names(conn):
    """(manufacturer canonical, normalised name) -> the name already stored.

    'DS-2' and 'DS 2' are the same instrument; reuse whatever the DB already
    calls it rather than adding a second spelling.
    """
    out = {}
    for canon, name in conn.execute(
            """SELECT m.canonical_name, i.name FROM instruments i
               JOIN manufacturers m ON m.id = i.manufacturer_id"""):
        out[(canon, re.sub(r"[^a-z0-9]", "", name.lower()))] = name
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    req = urllib.request.Request(SITEMAP, headers=UA)
    xml = urllib.request.urlopen(req, timeout=120).read()
    root = ET.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [e.text.strip() for e in root.findall(".//s:loc", ns) if e.text]

    conn = sqlite3.connect(DB_PATH)
    index = load_makers(conn)          # lowercase name -> canonical_name

    known = existing_names(conn)
    found, unmapped = {}, {}
    for url in urls:
        path = url.split("vintagesynth.com/", 1)[-1]
        path = path[len("index.php/"):] if path.startswith("index.php/") else path
        parts = [p for p in path.split("/") if p]
        if len(parts) != 2:
            continue
        maker_slug, model_slug = parts
        if maker_slug in SKIP_SLUGS or model_slug in SKIP_SLUGS:
            continue
        maker = SLUG_ALIASES.get(maker_slug.lower())
        if not maker:
            maker = index.get(maker_slug.replace("-", " ").lower())
        name = title_case(model_slug)
        if not maker:
            unmapped.setdefault(maker_slug, []).append(name)
            continue
        norm = re.sub(r"[^a-z0-9]", "", name.lower())
        if norm.endswith("0") and (maker, norm[:-1]) in known:
            continue                      # the site's own duplicate entries (-0 slugs)
        name = known.get((maker, norm), name)
        found.setdefault(maker, {}).setdefault(
            name, {"name": name, "source_url": url})

    batch = {"manufacturers": [
        {"canonical_name": maker,
         "instruments": sorted(items.values(), key=lambda e: e["name"])}
        for maker, items in sorted(found.items())]}
    text = json.dumps(batch, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        total = sum(len(m["instruments"]) for m in batch["manufacturers"])
        print(f"{total} instruments across {len(batch['manufacturers'])} manufacturers -> {args.out}")
    else:
        print(text)

    if unmapped:
        print(f"\n-- {len(unmapped)} unmapped maker slugs "
              f"({sum(len(v) for v in unmapped.values())} models behind them):", file=sys.stderr)
        for slug, models in sorted(unmapped.items(), key=lambda kv: -len(kv[1])):
            print(f"   {slug} ({len(models)})", file=sys.stderr)


if __name__ == "__main__":
    main()
