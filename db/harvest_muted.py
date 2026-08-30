#!/usr/bin/env python3
"""Harvest muted.io's synth list.

https://muted.io/synth-list/ is a single server-rendered HTML table -- brand,
model, release year, synthesis style, voice count, mono/poly, price, features,
and a link straight to the maker's own product page. robots.txt is fully open.

Small (95 rows, 17 brands) and skewed modern, so by Kristof's era priority it
is not the main haul. Two things make it worth a pass anyway:

* the model link is the MANUFACTURER'S OWN product page, which is the highest
  source tier we have -- and it is current, unlike the 2000s links harvested
  from vintagesynth;
* release year and synthesis style come as clean columns, no parsing of prose.

Writes two files: an instruments batch for db/ingest.py, and a pages-shaped
batch for db/ingest_links.py, so neither ingester needs a special case.

Usage:
  python3 db/harvest_muted.py --out-instruments db/batches/muted-instruments.json \
                              --out-links db/batches/muted-pages.json
"""

import argparse
import html
import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_wikipedia_instruments import load_makers                # noqa: E402

URL = "https://muted.io/synth-list/"
DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept-Language": "en-US,en;q=0.9"}

# Brand as printed on the page -> the name we hold. Nord is a BRAND of
# Clavia DMI, not a company of its own -- exactly the distinction the
# holding-company rule exists for.
BRAND_ALIASES = {
    "roland": "Roland Corporation",
    "korg": "Korg Inc.",
    "moog": "Moog Music",
    "waldorf": "Waldorf Music",
    "sequential": "Sequential",
    "akai": "Akai Professional",
    "nord": "Clavia",   # Nord is Clavia's brand, not a company
    "e-mu": "E-mu Systems",
}


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def rows_from(page):
    body = page[page.find("<tbody"):page.find("</tbody>")]
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 7:
            continue
        link = re.search(r'href="(https?://[^"]+)"', tds[1])
        yield {
            "brand": strip_tags(tds[0]),
            "model": re.sub(r"\s+", " ", strip_tags(tds[1])),
            "year": strip_tags(tds[2]),
            "synthesis": strip_tags(tds[3]),
            "voices": strip_tags(tds[4]),
            "polyphony": strip_tags(tds[5]),
            "price": strip_tags(tds[6]),
            "features": strip_tags(tds[7]) if len(tds) > 7 else "",
            "product_url": link.group(1) if link else None,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-instruments", required=True)
    ap.add_argument("--out-links", required=True)
    args = ap.parse_args()

    page = urllib.request.urlopen(
        urllib.request.Request(URL, headers=UA), timeout=45
    ).read().decode("utf-8", "replace")

    conn = sqlite3.connect(DB_PATH)
    index = load_makers(conn)
    existing = {c for (c,) in conn.execute("SELECT canonical_name FROM manufacturers")}

    by_maker, pages, unknown = {}, [], {}
    for r in rows_from(page):
        canon = BRAND_ALIASES.get(r["brand"].lower()) or index.get(r["brand"].lower())
        # A brand that only sits in discovery_queue is NOT created here. An
        # instrument list is not research; the maker gets its row when it is
        # actually researched, and re-running this batch then picks it up.
        # (An alias is a mapping, not a promise the target exists -- Nord maps
        # to Clavia, which is still only queued.)
        if canon not in existing:
            canon = None
        if not canon:
            unknown.setdefault(r["brand"], []).append(r["model"])
            continue
        # the table repeats the brand in some model names; the parent record
        # already says it (same rule as the vintagesynth harvest)
        model = re.sub(rf"^{re.escape(r['brand'])}\s+", "", r["model"], flags=re.I)
        entry = {"name": model, "source_url": URL}
        if re.fullmatch(r"\d{4}", r["year"] or ""):
            entry["year"] = int(r["year"])
        by_maker.setdefault(canon, {})[model.lower()] = entry

        if r["product_url"]:
            pages.append({
                "maker_slug": canon,          # already canonical, not a slug
                "model_slug": model,
                "display_name": f'{r["brand"]} {model}',
                "source_url": URL,
                "links": [{"url": r["product_url"],
                           "label": f'{r["brand"]} {model} product page',
                           "block": "links"}],
                "specs": {k: r[k] for k in
                          ("synthesis", "voices", "polyphony", "price", "features")
                          if r[k]},
            })

    batch = {"manufacturers": [
        {"canonical_name": canon, "instruments": sorted(v.values(),
                                                        key=lambda e: e["name"])}
        for canon, v in sorted(by_maker.items())]}
    Path(args.out_instruments).write_text(
        json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(args.out_links).write_text(
        json.dumps({"source": "muted.io", "pages": pages}, indent=2,
                   ensure_ascii=False), encoding="utf-8")

    total = sum(len(m["instruments"]) for m in batch["manufacturers"])
    print(f"{total} instruments across {len(batch['manufacturers'])} makers "
          f"-> {args.out_instruments}", file=sys.stderr)
    print(f"{len(pages)} product links -> {args.out_links}", file=sys.stderr)
    if unknown:
        print(f"\n-- {len(unknown)} brands not in the DB:", file=sys.stderr)
        for brand, models in sorted(unknown.items(), key=lambda kv: -len(kv[1])):
            print(f"   {brand} ({len(models)}): {', '.join(models[:4])}",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
