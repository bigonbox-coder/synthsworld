#!/usr/bin/env python3
"""Harvest synthmania.com -- one collector's gear pages, with audio demos.

Small (119 instrument posts) and it is one person's collection, not a
catalogue -- so it is not a coverage source. What makes it worth a pass:

* Every post is tagged with the BRAND and the PRODUCTION YEAR, and filed under
  a category that names the form factor and the technology
  ("Analog Polyphonic Synthesizer", "Rack Sampler", "Digital Drum Machine").
  That is phase-2 categorisation vocabulary arriving as structured taxonomy
  terms instead of prose to interpret.
* Each page carries audio demos of the actual instrument -- phase-3 material,
  and the one file type none of the other sources have.

WordPress, robots.txt open apart from /wp-admin, and a real sitemap.

Writes an instruments batch (db/ingest.py) and a pages-shaped batch
(db/ingest_links.py) holding the demo audio.

Usage:
  python3 db/harvest_synthmania.py --out-instruments db/batches/synthmania-instruments.json \
                                   --out-links db/batches/synthmania-pages.json
"""

import argparse
import html
import json
import re
import sqlite3
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maker_lookup import MakerLookup  # noqa: E402

SITEMAP = "https://synthmania.com/wp-sitemap-posts-post-1.xml"
DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
CACHE = Path(__file__).resolve().parent / "cache" / "synthmania"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_wikipedia_instruments import load_makers                 # noqa: E402

# The site catalogues its owner's whole studio, so its categories include
# things the instruments table deliberately excludes: effect units, sample and
# patch libraries, expansion cards. Same scope rule as everywhere else -- the
# MAKER can still be in scope (Alesis makes synths too), the PRODUCT is not.
OUT_OF_SCOPE = {
    "effect", "patch library", "sample library", "sound expansion card",
    "sound expansion board", "sound chip", "software", "mixer", "recorder",
    "amplifier", "speaker", "microphone", "audio interface", "controller",
}

BRAND_ALIASES = {
    "roland": "Roland Corporation", "korg": "Korg Inc.", "moog": "Moog Music",
    "akai": "Akai Professional", "emu": "E-mu Systems", "e-mu": "E-mu Systems",
    "arp": "ARP Instruments", "waldorf": "Waldorf Music",
    "kurzweil": "Kurzweil Music Systems", "sequential": "Sequential",
}


def fetch(url, key):
    path = CACHE / (key + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8")
    body = urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=45
    ).read().decode("utf-8", "replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    time.sleep(0.3)
    return body


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def parse_post(body, url):
    title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = re.sub(r"\s+", " ", strip_tags(title.group(1))) if title else None
    cats = [html.unescape(c) for c in
            re.findall(r'rel="category tag">([^<]+)</a>', body)]
    tags = [html.unescape(t) for t in re.findall(r'rel="tag">([^<]+)</a>', body)]
    years = [int(t) for t in tags if re.fullmatch(r"(19|20)\d{2}", t)]
    # the maker is the tag that is not a year and not a form-factor term
    brands = [t for t in tags if not re.fullmatch(r"(19|20)\d{2}", t)]
    audio = sorted({html.unescape(a) for a in
                    re.findall(r'https?://[^"\'<> ]+\.(?:mp3|wav)', body)})
    return {"url": url, "title": title, "categories": cats, "tags": tags,
            "brands": brands, "year": min(years) if years else None,
            "audio": audio}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-instruments", required=True)
    ap.add_argument("--out-links", required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    xml = urllib.request.urlopen(
        urllib.request.Request(SITEMAP, headers=UA), timeout=45).read()
    urls = [e.text for e in ET.fromstring(xml).findall(".//s:loc", NS)]
    if args.limit:
        urls = urls[:args.limit]
    print(f"{len(urls)} posts", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    index = load_makers(conn)
    lookup = MakerLookup(conn)
    existing = {c for (c,) in conn.execute("SELECT canonical_name FROM manufacturers")}

    by_maker, pages, unknown = {}, [], {}
    for i, url in enumerate(urls, 1):
        post = parse_post(fetch(url, url.rstrip("/").rsplit("/", 1)[-1]), url)
        if i % 25 == 0:
            print(f"  {i}/{len(urls)}", file=sys.stderr)
        if not post["title"]:
            continue
        canon = None
        for brand in post["brands"]:
            # Ugyanaz mint a vintagesynth-nel: a BRAND_ALIASES a hosszu alakot
            # adja, a kozos feloldo a mostani fonevet (nev-modell, 2026-09-02).
            cand = (lookup.canonical(BRAND_ALIASES.get(brand.lower()) or "")
                    or lookup.canonical(brand)
                    or index.get(brand.lower()))
            if cand in existing:
                canon = cand
                break
        if not canon:
            key = post["brands"][0] if post["brands"] else "?"
            unknown.setdefault(key, []).append(post["title"])
            continue
        # the post title repeats the brand; the parent record already says it
        model = post["title"]
        for brand in post["brands"]:
            model = re.sub(rf"^{re.escape(brand)}\s+", "", model, flags=re.I)
        entry = {"name": model, "source_url": url}
        if post["year"]:
            entry["year"] = post["year"]
        if post["categories"]:
            if post["categories"][0].strip().lower() in OUT_OF_SCOPE:
                continue
            entry["category"] = post["categories"][0]
        by_maker.setdefault(canon, {})[model.lower()] = entry

        if post["audio"]:
            pages.append({
                "maker_slug": canon, "model_slug": model,
                "display_name": post["title"], "source_url": url,
                "links": [{"url": a, "label": f"{model} audio demo",
                           "block": "resources"} for a in post["audio"][:12]],
                "specs": {"categories": ", ".join(post["categories"])},
            })

    batch = {"manufacturers": [
        {"canonical_name": c, "instruments": sorted(v.values(), key=lambda e: e["name"])}
        for c, v in sorted(by_maker.items())]}
    Path(args.out_instruments).write_text(
        json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(args.out_links).write_text(
        json.dumps({"source": "synthmania", "pages": pages}, indent=2,
                   ensure_ascii=False), encoding="utf-8")

    total = sum(len(m["instruments"]) for m in batch["manufacturers"])
    naudio = sum(len(p["links"]) for p in pages)
    print(f"{total} instruments across {len(batch['manufacturers'])} makers, "
          f"{naudio} audio demos", file=sys.stderr)
    if unknown:
        print(f"\n-- {len(unknown)} brands not held:", file=sys.stderr)
        for brand, models in sorted(unknown.items(), key=lambda kv: -len(kv[1])):
            print(f"   {brand} ({len(models)})", file=sys.stderr)


if __name__ == "__main__":
    main()
