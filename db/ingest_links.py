#!/usr/bin/env python3
"""Load a harvested link batch into external_links.

Input: the JSON written by harvest_vintagesynth_pages.py.

What it decides, all by rule -- no model, no page prose:

* Owner. A link whose domain is the manufacturer's own is attached to the
  MANUFACTURER (once, however many of its instrument pages carry it).
  Everything else is attached to the INSTRUMENT it was found on, because a
  retrofit vendor or a users' forum is about that one model.
* Type. manufacturer_official / community / service_mod / archive / samples /
  retailer / media / other, from the domain and the link's own label.

The official-site rule is deliberately narrow: the domain's own label must be
the maker's name, or the name plus a generic suffix (roland -> rolandus,
akai -> akaipro). Substring matching alone would call moogarchives.com Moog's
official site, which it is not.

Nothing here writes manufacturers.official_website. A third-party page saying
"Roland U.S." is a candidate, not evidence; promoting it needs the reachability
check and a review pass (see --report).

Usage:
  python3 db/ingest_links.py db/batches/vintagesynth-pages-1.json [--dry-run]
  python3 db/ingest_links.py --report        # official-site candidates
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harvest_vintagesynth import SLUG_ALIASES, title_case          # noqa: E402
from harvest_wikipedia_instruments import load_makers              # noqa: E402

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"

# Corporate boilerplate that never appears in a domain name.
NAME_NOISE = {"corporation", "corp", "inc", "incorporated", "ltd", "limited",
              "gmbh", "spa", "srl", "co", "company", "kk", "ab", "bv", "sa",
              "electronics", "electronic", "instruments", "instrument",
              "musical", "music", "audio", "systems", "system", "laboratories",
              "labs", "laboratory", "industries", "technologies", "factory",
              "radio", "modular", "the", "and", "of"}

# Suffixes a maker legitimately bolts onto its own name in a domain.
OFFICIAL_SUFFIXES = {"", "us", "usa", "uk", "eu", "jp", "de", "it", "music",
                     "musicgroup", "corp", "inc", "audio", "sound", "synth",
                     "synths", "instruments", "pro", "online", "official",
                     "group", "gear", "electronics"}

COMMUNITY = ("forum", "group", "board", "users", "userlist", "mailing",
             "society", "club", "fanpage", "yahoo", "reddit", "discord",
             "facebook", "wiki")
SERVICE = ("retrofit", "midi kit", "mod ", "mods", "upgrade", "repair",
           "service", "parts", "spare", "restoration", "kit")
ARCHIVE = ("archive", "museum", "history", "historic", "vintage synth preserv")
SAMPLES = ("sample", "patches", "patch", "sysex", "sounds", "soundset",
           "presets", "librarian", "editor")
RETAIL = ("shop", "store", "buy", "price", "reverb", "ebay", "sweetwater",
          "perfectcircuit", "cafepress", "amazon", "thomann")
MEDIA = ("review", "magazine", "sound on sound", "soundonsound", "youtube",
         "vimeo", "demo", "sonicstate", "keyboardmag")

ARCHIVE_DOMAINS = {"web.archive.org", "archive.org", "moogarchives.com",
                   "keyboardmuseum.com", "synthmuseum.com", "obsolete.com",
                   "synthfool.com", "museodelsynth.org"}


def domain_of(url):
    net = urllib.parse.urlsplit(url).netloc.lower()
    net = net.split("@")[-1].split(":")[0]
    return net[4:] if net.startswith("www.") else net


def domain_label(dom):
    """The registrable-ish label: roland.co.uk -> roland, emu.com -> emu."""
    parts = [p for p in dom.split(".") if p]
    if not parts:
        return ""
    # walk past common public-suffix pieces from the right
    tail = {"com", "net", "org", "co", "uk", "de", "it", "jp", "ru", "fr",
            "eu", "us", "nl", "se", "ch", "at", "au", "ca", "info", "io"}
    i = len(parts) - 1
    while i > 0 and parts[i] in tail:
        i -= 1
    return parts[i]


def name_key(name):
    """'E-mu Systems' -> 'emu'; 'Roland Corporation' -> 'roland'."""
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]
    kept = [w for w in words if w not in NAME_NOISE] or words
    return "".join(kept[:2]) if len(kept[0]) <= 2 else kept[0]


def is_official(dom, maker_name):
    key = name_key(maker_name)
    if not key or len(key) < 3:
        return False
    label = domain_label(dom)
    if label == key:
        return True
    if label.startswith(key) and label[len(key):] in OFFICIAL_SUFFIXES:
        return True
    return False


AUDIO_EXT = re.compile(r"\.(mp3|wav|flac|ogg|m4a|aiff?)(\?|$)", re.I)


def classify(url, label, dom, official):
    # A media FILE is not a media page: an .mp3 of the instrument is primary
    # material (phase 3), while a review or a video is a source to read.
    if AUDIO_EXT.search(url):
        return "audio_demo"
    if official:
        return "manufacturer_official"
    hay = f"{label or ''} {url}".lower()
    if dom in ARCHIVE_DOMAINS or any(w in hay for w in ARCHIVE):
        return "archive"
    if any(w in hay for w in COMMUNITY):
        return "community"
    if any(w in hay for w in SERVICE):
        return "service_mod"
    if any(w in hay for w in SAMPLES):
        return "samples"
    if any(w in hay for w in RETAIL):
        return "retailer"
    if any(w in hay for w in MEDIA):
        return "media"
    return "other"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def build_indexes(conn):
    makers = load_makers(conn)                     # lower name -> canonical
    ids = {c: i for i, c in conn.execute(
        "SELECT id, canonical_name FROM manufacturers")}
    by_url, by_name = {}, {}
    for iid, mid, iname, src in conn.execute(
            "SELECT id, manufacturer_id, name, source_url FROM instruments"):
        if src:
            by_url[src.rstrip("/")] = iid
        by_name[(mid, norm(iname))] = iid
    return makers, ids, by_url, by_name


def resolve_maker(slug, makers):
    canon = SLUG_ALIASES.get(slug.lower())
    if canon:
        return canon
    return makers.get(slug.replace("-", " ").lower())


PLACEHOLDER = re.compile(
    r"maintenance|under[-_]?construction|coming[-_ ]?soon|parked|parking|"
    r"suspended|account[-_]?disabled|domain[-_]?for[-_]?sale", re.I)


def promote_official(conn):
    """Fill manufacturers.official_website where it is empty.

    Only from a link on the maker's OWN domain that answered (live/redirected/
    blocked -- a WAF refusing us still proves the host is there), and only when
    every such link agrees on one domain. The stored value is the domain root,
    not whatever deep product page we happened to find it on.

    A page on the manufacturer's own site is the top source tier, so this needs
    no second source -- but it is still written to facts_sources, and it never
    touches confidence_level: the company itself is still unresearched.
    """
    rows = conn.execute("""
        SELECT m.id, m.canonical_name, l.domain, l.url, l.found_on, l.final_url
        FROM manufacturers m JOIN external_links l ON l.manufacturer_id = m.id
        WHERE (m.official_website IS NULL OR m.official_website = '')
          AND l.link_type = 'manufacturer_official'
          AND l.status IN ('live', 'redirected', 'blocked')
        ORDER BY m.canonical_name""").fetchall()
    by_maker = {}
    for mid, canon, domain, url, found_on, final_url in rows:
        # A domain that resolves is not the same as a site that is there.
        # E-mu's emu.com answers, but every path lands on maintenance.html --
        # recording that as the official site would look like evidence and be
        # worth nothing.
        if final_url and PLACEHOLDER.search(final_url):
            print(f"SKIP {canon}: {domain} redirects to a placeholder "
                  f"({final_url})", file=sys.stderr)
            continue
        by_maker.setdefault((mid, canon), []).append((domain, url, found_on))

    done = 0
    for (mid, canon), hits in by_maker.items():
        domains = {d for d, _, _ in hits}
        if len(domains) != 1:
            print(f"SKIP {canon}: {len(domains)} candidate domains {sorted(domains)}",
                  file=sys.stderr)
            continue
        domain = domains.pop()
        site = f"https://{domain}/"
        found_on = hits[0][2]
        with conn:
            conn.execute(
                """UPDATE manufacturers SET official_website = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?""",
                (site, mid))
            conn.execute(
                """INSERT INTO facts_sources
                     (manufacturer_id, field_name, value, source_url, source_tier)
                   VALUES (?, 'official_website', ?, ?, 'manufacturer_official')""",
                (mid, site, found_on))
        print(f"SET  {canon}: {site}", file=sys.stderr)
        done += 1
    print(f"{done} official websites filled", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--promote-official", action="store_true",
                    help="fill an EMPTY official_website from a live own-domain link")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    if args.report:
        rows = conn.execute("""
            SELECT m.canonical_name, m.official_website, l.url, l.label,
                   l.status, COUNT(*) c
            FROM external_links l JOIN manufacturers m ON m.id = l.manufacturer_id
            WHERE l.link_type = 'manufacturer_official'
            GROUP BY m.id, l.url ORDER BY m.canonical_name, c DESC""").fetchall()
        for canon, have, url, label, status, c in rows:
            flag = "have" if have else "EMPTY"
            print(f"{canon:38} {flag:5} {status:10} {url}  [{label}]")
        print(f"\n{len(rows)} official-site candidates", file=sys.stderr)
        return

    if args.promote_official:
        promote_official(conn)
        return

    if not args.batch:
        ap.error("a batch file is required unless --report is used")

    data = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    source_name = data.get("source", "unknown")
    makers, maker_ids, by_url, by_name = build_indexes(conn)

    rows, unmapped_makers, unmatched_instruments = [], {}, []
    seen_maker_links = set()
    for page in data["pages"]:
        if not page["links"]:
            continue
        canon = resolve_maker(page["maker_slug"], makers)
        if not canon:
            unmapped_makers.setdefault(page["maker_slug"], 0)
            unmapped_makers[page["maker_slug"]] += len(page["links"])
            continue
        mid = maker_ids.get(canon)
        src = page["source_url"].rstrip("/")
        iid = by_url.get(src) or by_url.get(src.replace("/index.php", ""))
        if not iid:
            for cand in (page.get("display_name", ""), title_case(page["model_slug"])):
                # the site prints "Roland Jupiter-8"; we store "Jupiter-8"
                cand = re.sub(rf"^{re.escape(canon.split()[0])}\s+", "", cand,
                              flags=re.I)
                iid = by_name.get((mid, norm(cand)))
                if iid:
                    break
        if not iid:
            unmatched_instruments.append(page["source_url"])

        for link in page["links"]:
            url = link["url"]
            dom = domain_of(url)
            if not dom or dom.endswith("vintagesynth.com"):
                continue
            official = is_official(dom, canon)
            ltype = classify(url, link.get("label"), dom, official)
            if official:
                key = (mid, url)
                if key in seen_maker_links:
                    continue
                seen_maker_links.add(key)
                rows.append((mid, None, url, dom, link.get("label"), ltype,
                             page["source_url"], source_name))
            elif iid:
                rows.append((None, iid, url, dom, link.get("label"), ltype,
                             page["source_url"], source_name))
            else:
                rows.append((mid, None, url, dom, link.get("label"), ltype,
                             page["source_url"], source_name))

    print(f"{len(rows)} link rows ready "
          f"({sum(1 for r in rows if r[5] == 'manufacturer_official')} official-site)",
          file=sys.stderr)
    if unmapped_makers:
        print(f"{len(unmapped_makers)} maker slugs not in the DB "
              f"({sum(unmapped_makers.values())} links behind them)", file=sys.stderr)
    if unmatched_instruments:
        print(f"{len(unmatched_instruments)} pages matched a maker but no instrument",
              file=sys.stderr)

    if args.dry_run:
        return

    with conn:
        conn.executemany("""
            INSERT INTO external_links
              (manufacturer_id, instrument_id, url, domain, label, link_type,
               found_on, source_name)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT DO NOTHING""", rows)
    total = conn.execute("SELECT COUNT(*) FROM external_links").fetchone()[0]
    print(f"external_links now holds {total} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
