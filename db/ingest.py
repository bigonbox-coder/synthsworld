#!/usr/bin/env python3
"""Ingest a research batch (JSON) into the Synthsworld database.

Takes the structured output of a phase-1 manufacturer research pass and writes
it into `manufacturers`, `facts_sources`, `manufacturer_name_history`,
`manufacturer_relations` and `discovery_queue`, applying the project's
confidence rules. Stdlib only.

Usage:  python3 db/ingest.py batch.json [--dry-run]

Expected JSON shape:

    {"manufacturers": [
       {"canonical_name": "...", "country": "...", "official_website": "...",
        "status": "active|defunct|acquired",
        "founded_year": 1969, "ended_year": null, "city": "Simmern",
        "founders": "Wilhelm-Erich Franz, Reinhard Franz",
        "short_history": "...", "long_history": "...",
        "name_history": [{"name": "...", "start_year": 1969, "end_year": 1974}],
        "instruments": ["SX-1000", {"name": "DK 80", "year": 1985,
                                    "category": "synthesizer"}],
        "relations": [{"related_company": "...", "relation_type": "acquired_by",
                       "year": 1987}],
        "sources": [{"field_name": "country", "value": "...",
                     "source_url": "https://...",
                     "source_tier": "manufacturer_official|wikidata|other"}],
        "conflicts": ["founding year: 1969 per official site vs 1970 per Wikipedia"],
        "review_note": "optional note recorded on the queue row WITHOUT downgrading\n                        confidence -- for detail-level observations (e.g. a product\n                        release year that sources disagree on) that do not touch a\n                        stored manufacturer field",
        "queue_name": "optional discovery_queue.manufacturer_name to close"}
    ]}

Confidence rules (see the synthsworld-manufacturer-discovery skill):
  * a field backed by a `manufacturer_official` source counts as confirmed;
  * any other single source is NOT enough -- a second, independent (different
    URL) source agreeing on the same value is required;
  * a manufacturer rolls up to `needs_review` if any conflict was reported or
    any CORE field failed to reach confirmed; otherwise `confirmed`.
  * stub rows created for related companies start as `unresearched`, never
    `confirmed` and never `needs_review`.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
CORE_FIELDS = ("country", "status", "short_history")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def normalise(value):
    """Loose comparison key so 'United States' and 'united states.' agree."""
    return " ".join(str(value or "").strip().lower().rstrip(".").split())


NARRATIVE_FIELDS = ("short_history", "long_history")


def field_confidence(sources, field_name):
    """Return 'confirmed' or 'needs_review' for one field, per the rules above."""
    rows = [s for s in sources if s.get("field_name") == field_name]
    if not rows:
        return "needs_review"
    if any(s.get("source_tier") == "manufacturer_official" for s in rows):
        return "confirmed"
    if field_name in NARRATIVE_FIELDS:
        # A history text is an original synthesis, so two sources never carry the
        # same string. Here "two agreeing sources" means two distinct sources
        # the narrative was actually built from.
        return "confirmed" if len({r.get("source_url") for r in rows}) >= 2 else "needs_review"
    # Two independent sources (distinct URLs) agreeing on the same value.
    by_value = {}
    for s in rows:
        by_value.setdefault(normalise(s.get("value")), set()).add(s.get("source_url"))
    return "confirmed" if any(len(urls) >= 2 for urls in by_value.values()) else "needs_review"


def roll_up(entry):
    """Manufacturer-level confidence + the note explaining a needs_review."""
    reasons = list(entry.get("conflicts") or [])
    sources = entry.get("sources") or []
    for field in CORE_FIELDS:
        if entry.get(field) and field_confidence(sources, field) != "confirmed":
            reasons.append(f"{field}: single non-official source only")
    return ("needs_review" if reasons else "confirmed"), "; ".join(reasons)


def find_manufacturer(conn, name):
    row = conn.execute(
        "SELECT id FROM manufacturers WHERE lower(canonical_name) = lower(?)", (name,)
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        """SELECT manufacturer_id FROM manufacturer_name_history
           WHERE lower(name) = lower(?)""",
        (name,),
    ).fetchone()
    return row[0] if row else None


def upsert_manufacturer(conn, entry, confidence, conflicts):
    """Insert or update on canonical_name; never create a duplicate company."""
    ts = now()
    mid = find_manufacturer(conn, entry["canonical_name"])
    if mid is not None and not entry.get("sources"):
        # An entry carrying no sources is an addition to an existing record (a
        # model list, say), not a research pass. It has no evidence behind it,
        # so it must not restate confidence in either direction -- without this
        # guard an instruments-only batch silently promotes a needs_review
        # record to confirmed.
        confidence = conn.execute(
            "SELECT confidence_level FROM manufacturers WHERE id = ?", (mid,)
        ).fetchone()[0]
    if mid is not None and confidence == "needs_review" and not conflicts:
        # A thinner re-pass must not demote an already-confirmed record: only a
        # real source conflict does that, never merely fewer sources this time.
        previous = conn.execute(
            "SELECT confidence_level FROM manufacturers WHERE id = ?", (mid,)
        ).fetchone()[0]
        if previous == "confirmed":
            confidence = "confirmed"
    cols = ("country", "official_website", "status", "short_history", "long_history",
            "founded_year", "ended_year", "city", "founders", "entity_type")
    # entity_type is NOT NULL with a default, so an entry that says nothing
    # about it must still insert as a company rather than blow up on NULL.
    defaults = {"entity_type": "company"}
    if mid is None:
        placeholders = ", ".join(["?"] * (len(cols) + 4))
        conn.execute(
            f"""INSERT INTO manufacturers
                (canonical_name, {', '.join(cols)}, confidence_level, created_at, updated_at)
                VALUES ({placeholders})""",
            (entry["canonical_name"],
             *[entry.get(c) if entry.get(c) is not None else defaults.get(c)
               for c in cols],
             confidence, ts, ts),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0], "inserted", confidence
    # Update in place, but never blank out an existing value with a missing one.
    sets, params = [], []
    for c in cols:
        if entry.get(c):
            sets.append(f"{c} = ?")
            params.append(entry[c])
    sets += ["confidence_level = ?", "updated_at = ?"]
    params += [confidence, ts, mid]
    conn.execute(f"UPDATE manufacturers SET {', '.join(sets)} WHERE id = ?", params)
    return mid, "updated", confidence


def stub_manufacturer(conn, name):
    """Minimal `unresearched` row for a company surfaced only via a relation."""
    ts = now()
    conn.execute(
        """INSERT INTO manufacturers (canonical_name, confidence_level, created_at, updated_at)
           VALUES (?, 'unresearched', ?, ?)""",
        (name, ts, ts),
    )
    mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    queued = conn.execute(
        "SELECT id FROM discovery_queue WHERE lower(manufacturer_name) = lower(?)", (name,)
    ).fetchone()
    if not queued:
        conn.execute(
            """INSERT INTO discovery_queue (manufacturer_name, status, created_at, updated_at)
               VALUES (?, 'found', ?, ?)""",
            (name, ts, ts),
        )
    return mid


def add_sources(conn, mid, sources):
    """Append-only: an existing (field, url) pair is never overwritten."""
    added = 0
    for s in sources:
        exists = conn.execute(
            """SELECT 1 FROM facts_sources
               WHERE manufacturer_id = ? AND field_name = ? AND source_url = ?""",
            (mid, s.get("field_name"), s.get("source_url")),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO facts_sources
               (manufacturer_id, field_name, value, source_url, source_tier, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (mid, s.get("field_name"), s.get("value"), s.get("source_url"),
             s.get("source_tier", "other"), now()),
        )
        added += 1
    return added


def add_name_history(conn, mid, names):
    added = 0
    for n in names:
        if not n.get("name"):
            continue
        exists = conn.execute(
            """SELECT 1 FROM manufacturer_name_history
               WHERE manufacturer_id = ? AND lower(name) = lower(?)""",
            (mid, n["name"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO manufacturer_name_history (manufacturer_id, name, start_year, end_year)
               VALUES (?, ?, ?, ?)""",
            (mid, n["name"], n.get("start_year"), n.get("end_year")),
        )
        added += 1
    return added


def add_instruments(conn, mid, instruments):
    """Model names for one manufacturer. Names only -- specifications are phase 2.

    Accepts either a bare string or {"name", "year", "category", "source_url"},
    because most passes will only have the name.
    """
    added = 0
    for item in instruments:
        entry = {"name": item} if isinstance(item, str) else dict(item or {})
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        exists = conn.execute(
            "SELECT 1 FROM instruments WHERE manufacturer_id = ? AND lower(name) = lower(?)",
            (mid, name),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO instruments (manufacturer_id, name, year, category, source_url)
               VALUES (?, ?, ?, ?, ?)""",
            (mid, name, entry.get("year"), entry.get("category"), entry.get("source_url")),
        )
        added += 1
    return added


def add_relations(conn, mid, relations):
    added, stubbed = 0, []
    for r in relations:
        other = r.get("related_company")
        if not other:
            continue
        other_id = find_manufacturer(conn, other)
        if other_id is None:
            other_id = stub_manufacturer(conn, other)
            stubbed.append(other)
        if other_id == mid:
            continue
        exists = conn.execute(
            """SELECT 1 FROM manufacturer_relations
               WHERE manufacturer_id = ? AND related_manufacturer_id = ? AND relation_type = ?""",
            (mid, other_id, r.get("relation_type")),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO manufacturer_relations
               (manufacturer_id, related_manufacturer_id, relation_type, year)
               VALUES (?, ?, ?, ?)""",
            (mid, other_id, r.get("relation_type"), r.get("year")),
        )
        added += 1
    return added, stubbed


def close_queue(conn, entry, confidence, note):
    """Advance the queue row this research pass was answering."""
    names = [entry.get("queue_name"), entry["canonical_name"]]
    names += [n.get("name") for n in entry.get("name_history") or []]
    for name in [n for n in names if n]:
        row = conn.execute(
            """SELECT id FROM discovery_queue
               WHERE lower(manufacturer_name) = lower(?) AND status != 'done'""",
            (name,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE discovery_queue SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
                ("done" if confidence == "confirmed" else "needs_review",
                 note or None, now(), row[0]),
            )
            return name
    return None


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in argv
    if not args:
        print(__doc__)
        return 1

    batch = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    for entry in batch["manufacturers"]:
        confidence, note = roll_up(entry)
        # upsert returns the confidence actually stored, which differs from the
        # rolled-up one when the guards above keep an existing value.
        mid, action, confidence = upsert_manufacturer(
            conn, entry, confidence, entry.get('conflicts') or [])
        facts = add_sources(conn, mid, entry.get("sources") or [])
        names = add_name_history(conn, mid, entry.get("name_history") or [])
        rels, stubbed = add_relations(conn, mid, entry.get("relations") or [])
        insts = add_instruments(conn, mid, entry.get("instruments") or [])
        extra = entry.get("review_note")
        full_note = "; ".join(n for n in (note, extra) if n)
        closed = close_queue(conn, entry, confidence, full_note)
        print(f"{entry['canonical_name']:<34} id={mid:<4} {action:<8} {confidence}")
        print(f"    facts+{facts} names+{names} relations+{rels} instruments+{insts} "
              f"queue={closed or 'no row'}")
        if stubbed:
            print(f"    new unresearched stubs: {', '.join(stubbed)}")
        if note:
            print(f"    needs_review: {note}")

    if dry_run:
        conn.rollback()
        print("\n-- dry run, rolled back --")
    else:
        conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
