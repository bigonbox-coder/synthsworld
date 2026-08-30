#!/usr/bin/env python3
"""Harvest Roland's own Updates & Drivers index.

https://www.roland.com/us/support/updates_drivers/ is server-rendered and
links to a downloads page for every product Roland still supports -- 567 of
them, shaped /us/support/by_product/<slug>/updates_drivers/. robots.txt
disallows /support/ and /<region>/support/knowledge_base/, but NOT this path.

This is the manufacturer's own site, so anything behind these links is
top-tier: firmware, drivers and manuals straight from the maker. It is
therefore the natural entry point for phase 3 (documents), which has no table
yet -- so this pass stops at recording the per-product support URL as an
official link on the instrument we already hold.

The index also NAMES each product's type in the link text -- "Programmable
Polyphonic Synthesizer", "Rhythm Composer", "Digital Sampler", "Combo Organ",
"MIDI Keyboard Controller". That is the manufacturer's own words about its own
product, so scope can be decided on evidence instead of on a guess about what a
model number means. Three buckets: IN (created), OUT (dropped), ASK (neither --
listed for Kristóf, because they are a scope decision and not mine to make).

Usage:
  python3 db/harvest_roland_support.py --out db/batches/roland-support.json
"""

import argparse
import html
import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

INDEX = "https://www.roland.com/us/support/updates_drivers/"
BASE = "https://www.roland.com"
MAKER = "Roland Corporation"
DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept-Language": "en-US,en;q=0.9"}


# Decided on Roland's OWN descriptor, never on the model number.
IN_SCOPE = re.compile(
    r"synthesi[sz]er|synth\b|synth module|sampler|sampling|groovebox|"
    r"rhythm (composer|performer|machine)|sequencer|workstation|organ|"
    r"stage piano|sound canvas", re.I)
# 'Drum Sound Module' and 'Percussion Sound Module' are V-Drums brains, not
# drum machines -- they go to ASK, so 'sound module' must not match them here.
SOUND_MODULE = re.compile(r"(?<!drum )(?<!percussion )sound module|"
                          r"\bsynth module\b", re.I)
OUT_OF_SCOPE = re.compile(
    r"interface|controller|amplifier|accordion|wind instrument|recorder|"
    r"mixer|trigger|monitor|speaker|switcher|camera|expansion|foot|"
    r"\bpad\b|announcement|dj\b|guitar amp", re.I)


def bucket(descriptor):
    if not descriptor:
        return "ask"
    if OUT_OF_SCOPE.search(descriptor):
        return "out"
    if IN_SCOPE.search(descriptor) or SOUND_MODULE.search(descriptor):
        return "in"
    return "ask"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    page = urllib.request.urlopen(
        urllib.request.Request(INDEX, headers=UA), timeout=45
    ).read().decode("utf-8", "replace")
    products = {}
    for slug, text in re.findall(
            r"""<a[^>]+href=["']/us/support/by_product/([^/"']+)/updates_drivers/["'][^>]*>(.*?)</a>""",
            page, re.S):
        parts = [p.strip() for p in
                 re.split(r"\t+|\s{2,}", html.unescape(re.sub(r"<[^>]+>", "\t", text)))
                 if p.strip()]
        products.setdefault(slug, (parts[0] if parts else slug,
                                   parts[1] if len(parts) > 1 else ""))
    slugs = sorted(products)
    print(f"{len(slugs)} products in Roland's own support index", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id FROM manufacturers WHERE canonical_name = ?", (MAKER,)).fetchone()
    if not row:
        sys.exit(f"{MAKER} is not in the database")
    mid = row[0]
    held = {norm(n): n for (n,) in conn.execute(
        "SELECT name FROM instruments WHERE manufacturer_id = ?", (mid,))}

    pages, new_instruments, ask, out = [], [], [], []
    for slug in slugs:
        roland_name, descriptor = products[slug]
        url = f"{BASE}/us/support/by_product/{slug}/updates_drivers/"
        name = held.get(norm(slug)) or held.get(norm(roland_name))
        if not name:
            b = bucket(descriptor)
            if b == "out":
                out.append((roland_name, descriptor))
                continue
            if b == "ask":
                ask.append((roland_name, descriptor))
                continue
            name = roland_name
            new_instruments.append({"name": name, "source_url": url,
                                    "category": descriptor or None})
        pages.append({
            "maker_slug": MAKER, "model_slug": name, "display_name": name,
            "source_url": INDEX,
            "links": [{"url": url, "label": f"{name} updates & drivers (Roland)",
                       "block": "links"}],
            "specs": {"roland_descriptor": descriptor} if descriptor else {},
        })

    Path(args.out).write_text(
        json.dumps({"source": "roland-support", "pages": pages,
                    "ask": [{"name": n, "descriptor": d} for n, d in ask],
                    "out_of_scope": [{"name": n, "descriptor": d} for n, d in out]},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    inst_path = Path(args.out).with_name(Path(args.out).stem + "-instruments.json")
    inst_path.write_text(json.dumps(
        {"manufacturers": [{"canonical_name": MAKER,
                            "instruments": sorted(new_instruments,
                                                  key=lambda e: e["name"])}]},
        indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(pages) - len(new_instruments)} matched instruments we hold, "
          f"{len(new_instruments)} new in-scope products -> {inst_path.name}",
          file=sys.stderr)
    print(f"{len(out)} dropped as out of scope, {len(ask)} left for Kristof to "
          f"decide (in the batch file under 'ask')", file=sys.stderr)


if __name__ == "__main__":
    main()
