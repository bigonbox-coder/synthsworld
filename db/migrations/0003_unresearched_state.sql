-- Add a third confidence_level state: 'unresearched'. Distinguishes a
-- placeholder stub (a manufacturer only known because another manufacturer's
-- research mentioned it as a relation, but never itself researched -- no
-- country/short_history/facts_sources) from 'needs_review' (research WAS
-- attempted, but sources conflict or only a single non-official source
-- exists). Before this migration the two were conflated, which is why a
-- huge, obviously-real manufacturer (Yamaha) could sit visually
-- indistinguishable from a genuinely uncertain fact.
--
-- SQLite can't ALTER a CHECK constraint in place -- standard recreate-table
-- pattern: new table with the updated constraint, copy all rows verbatim,
-- drop the old table, rename the new one into place. Migrations stay
-- additive-only by convention: this file is new, 0001/0002 are untouched.

PRAGMA foreign_keys=OFF;

CREATE TABLE manufacturers_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT NOT NULL UNIQUE,
  country TEXT,
  short_history TEXT,
  official_website TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'defunct', 'acquired')),
  confidence_level TEXT NOT NULL DEFAULT 'unresearched' CHECK (confidence_level IN ('confirmed', 'needs_review', 'unresearched')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO manufacturers_new (id, canonical_name, country, short_history, official_website, status, confidence_level, created_at, updated_at)
SELECT id, canonical_name, country, short_history, official_website, status, confidence_level, created_at, updated_at FROM manufacturers;

DROP TABLE manufacturers;
ALTER TABLE manufacturers_new RENAME TO manufacturers;

-- Default for genuinely new rows now created going forward is 'unresearched'
-- (was 'needs_review') -- a fresh stub has no research behind it at all.

PRAGMA foreign_keys=ON;

-- Data correction: any row that is a pure stub (no country, no short_history,
-- and zero facts_sources rows) was mis-tagged at creation time -- some ended
-- up 'confirmed' (bug), most 'needs_review' (not quite right either, since
-- no research was ever attempted). Reclassify all of them as 'unresearched'.
UPDATE manufacturers
SET confidence_level = 'unresearched'
WHERE country IS NULL
  AND short_history IS NULL
  AND id NOT IN (SELECT DISTINCT manufacturer_id FROM facts_sources);
