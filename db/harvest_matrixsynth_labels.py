#!/usr/bin/env python3
"""Mine MATRIXSYNTH's label index for manufacturer names.

https://www.matrixsynth.com/p/archives.html carries a <select> of every label
the blog has ever used -- 6175 of them, each with its post count. The blog tags
by maker, so this is the densest brand index we have found: Roland 34651,
Korg 27008, Moog 22038 ... down a very long tail. robots.txt is empty (no
restrictions), and one page fetch gets the whole thing.

The counts matter as much as the names: a label with 300 posts is a real
manufacturer somebody writes about, a label with 2 is usually a typo, a model
name or a one-off topic.

Labels are NOT all manufacturers -- Video, Auctions, DIY, eurorack, iOS are
topics. Two filters run: a topical stoplist, and a shape check. What survives
is reported, not silently queued: this is a candidate list for review.

Note for anyone re-parsing a Blogger page: the markup uses SINGLE quotes for
attributes. An href="..." regex finds 46 links here and misses 16000.

Usage:
  python3 db/harvest_matrixsynth_labels.py --min-count 50
  python3 db/harvest_matrixsynth_labels.py --min-count 50 --queue   # seed them
"""

import argparse
import html
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

URL = "https://www.matrixsynth.com/p/archives.html"
DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}

# Topical labels, not companies. Matched case-insensitively, exact.
STOP = {
    "video", "auctions", "featured", "diy", "reverb", "matrixsynth members",
    "soft synths", "synth tutorials", "ios", "news", "audio", "new", "ebay",
    "namm", "events", "new modules", "scans", "circuit bending", "interviews",
    "synth guts", "superbooth", "updates", "exclusive", "eurorack", "modular",
    "android", "app", "apps", "vst", "au", "aax", "plug-in", "plugins",
    "sequencer", "sequencers", "drum machine", "drum machines", "sampler",
    "samplers", "synthesizer", "synthesizers", "synth", "synths", "vintage",
    "analog", "analogue", "digital", "midi", "cv", "gate", "patch", "patches",
    "presets", "firmware", "manual", "manuals", "tutorial", "tutorials",
    "demo", "demos", "review", "reviews", "interview", "kickstarter",
    "black friday", "sale", "sales", "giveaway", "contest", "rip", "obituary",
    "music", "musicians", "artists", "live", "performance", "documentary",
    "film", "tv", "advert", "adverts", "ads", "catalog", "catalogs",
    "brochure", "brochures", "poster", "posters", "software", "hardware",
    "mobile", "iphone", "ipad", "mac", "windows", "linux", "raspberry pi",
    "arduino", "teensy", "3d printing", "case", "cases", "power supply",
    "moogfest", "knobcon", "synthplex", "messe", "musikmesse", "winter namm",
    # computers and platforms, not instrument makers
    "c64", "sid", "atari", "commodore", "apple", "bbc", "nintendo", "amiga",
    "zx spectrum", "msx", "gameboy", "game boy",
    # DAWs, hosts and controllers-as-software
    "ableton", "bitwig", "pure data", "max/msp", "maxmsp", "touchosc",
    "bidule", "fruity loops", "reaktor", "supercollider", "csound",
    # shops, auction houses and channels, not manufacturers
    "perfect circuit", "vemia", "thonk", "djtechtools", "lmnc", "vcv",
    "reverb.com", "sweetwater", "thomann", "andertons",
}

# Shapes that are never a company name. The "New ..." and "Synth ..." families
# are the blog's own editorial buckets (New in 2015, Synth Babes, Synth Books),
# so they are matched as patterns rather than listed one by one.
BAD_SHAPE = re.compile(r"^[\W\d]+$|^.{1,2}$|^#|^\$")
STOP_PATTERNS = re.compile(
    r"^new\b|^synth (babes|cats|chicks|art|bling|books|techs|humor|porn|p0rn)$"
    r"|^new in \d{4}$|^top \d|^\d{4}$|^holidays?$|^custom$|^rare$|^weird$"
    r"|^oddball$|^strange$|^cool$|^funny$|^meme|^best of|^this day"
    # trade shows and meetups, with or without a year: NAMM2014, Superbooth19
    r"|^(namm|superbooth|musikmesse|messe|synthfest|soundmit|knobcon|synthplex|"
    r"happy knobbing|pnw synth gathering|synth gathering)\s*\d*$"
    # the blog's own tags
    r"|^matrixsynth"
    # topic buckets that survive the word list
    r"|^synth (albums|ts|dogs|movies|cds|museums|cake|tv|kids)$"
    r"|^(video processing|art installations|studio tours|documentaries|"
    r"musique concrete|speech synthesis|test equipment|guitar synths|"
    r"alternate (controllers|keyboards)|chiptune|theremin|keytar|"
    r"oscilloscopes|breadboard|multitouch|steampunk|politics|nature|"
    r"outdoors|halloween|star wars|miniature|mechanical|online|free|"
    r"contests|teasers|russian|soviet|frac|scans)$", re.I)


def labels(page):
    """(label, post count) for every option in the archive's label select."""
    out = {}
    for _, text in re.findall(
            r"<option[^>]*value=['\"]([^'\"]*)['\"][^>]*>(.*?)</option>",
            page, re.S):
        t = html.unescape(re.sub(r"\s+", " ", text)).strip()
        m = re.match(r"^(.*?)\s*\((\d+)\)$", t)
        if m:
            out[m.group(1).strip()] = int(m.group(2))
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def known_names(conn):
    """Normalised forms of every maker name we already hold or have queued.

    Prefix matching in BOTH directions, because the blog's label is usually
    the short trade name while we store the legal one: 'Buchla' vs 'Buchla
    Electronic Musical Instruments', 'Emu' vs 'E-mu Systems'. Without this,
    the biggest names in the list all look like new discoveries.
    """
    names = set()
    for sql in ("SELECT canonical_name FROM manufacturers",
                "SELECT name FROM manufacturer_name_history",
                "SELECT manufacturer_name FROM discovery_queue"):
        names |= {norm(n) for (n,) in conn.execute(sql) if n}
    return {n for n in names if n}


def is_known(label, known):
    n = norm(label)
    if not n:
        return True
    if n in known:
        return True
    # 3 characters is deliberate: ARP, EMS, EDP, DSI and Emu are all real
    # makers we already hold under a longer legal name.
    if len(n) >= 3:
        return any(k.startswith(n) or n.startswith(k) for k in known if len(k) >= 3)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=50)
    ap.add_argument("--queue", action="store_true",
                    help="seed the surviving candidates into discovery_queue")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    page = urllib.request.urlopen(
        urllib.request.Request(URL, headers=UA), timeout=90
    ).read().decode("utf-8", "replace")
    found = labels(page)
    print(f"{len(found)} labels on the page", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    known = known_names(conn)

    candidates = []
    for name, count in sorted(found.items(), key=lambda kv: -kv[1]):
        if count < args.min_count:
            break
        if (name.lower() in STOP or BAD_SHAPE.match(name)
                or STOP_PATTERNS.search(name)):
            continue
        if is_known(name, known):
            continue
        candidates.append((name, count))
    if args.limit:
        candidates = candidates[:args.limit]

    for name, count in candidates:
        print(f"{count:7}  {name}")
    print(f"\n{len(candidates)} unknown labels at >= {args.min_count} posts",
          file=sys.stderr)

    if args.queue:
        with conn:
            conn.executemany(
                """INSERT INTO discovery_queue (manufacturer_name, notes)
                   VALUES (?, ?) ON CONFLICT DO NOTHING""",
                [(n, f"matrixsynth label, {c} posts") for n, c in candidates])
        total = conn.execute(
            "SELECT COUNT(*) FROM discovery_queue WHERE status='found'").fetchone()[0]
        print(f"discovery_queue now holds {total} 'found' rows", file=sys.stderr)


if __name__ == "__main__":
    main()
