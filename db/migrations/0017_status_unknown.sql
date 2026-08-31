-- manufacturers.status: add 'unknown'.
--
-- The column was NOT NULL with three values and a DEFAULT of 'active'. That
-- default is a claim, and for the obscure makers now entering the database it
-- is usually a false one. Pollard Industries is the case that forced this:
-- its only source is the Wikipedia article on the Syndrum, which says what the
-- company made and never says whether it still exists. The choice was to
-- invent 'defunct', to let the default assert 'active' about a company nobody
-- has heard from since the early 1980s, or to say we do not know.
--
-- The project's rule is that a fact needs a source, and silence is not
-- evidence. So: we say we do not know. 'unknown' is not a research failure to
-- be cleaned up later, it is the honest value when the sources are silent, and
-- it keeps `status` out of the confirmed-fields count until something states
-- it.
--
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt. Column
-- order, defaults and every other constraint are preserved exactly; only the
-- status CHECK changes. Foreign keys are switched off for the swap, as SQLite
-- requires, and switched back on after.
PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

CREATE TABLE manufacturers_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT NOT NULL UNIQUE,
  country TEXT,
  short_history TEXT,
  official_website TEXT,
  status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (status IN ('active', 'defunct', 'acquired', 'unknown')),
  confidence_level TEXT NOT NULL DEFAULT 'unresearched'
    CHECK (confidence_level IN ('confirmed', 'needs_review', 'unresearched')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  long_history TEXT,
  founded_year INTEGER,
  ended_year INTEGER,
  city TEXT,
  founders TEXT,
  entity_type TEXT NOT NULL DEFAULT 'company'
    CHECK (entity_type IN ('company', 'individual'))
);

INSERT INTO manufacturers_new
  (id, canonical_name, country, short_history, official_website, status,
   confidence_level, created_at, updated_at, long_history, founded_year,
   ended_year, city, founders, entity_type)
SELECT
   id, canonical_name, country, short_history, official_website, status,
   confidence_level, created_at, updated_at, long_history, founded_year,
   ended_year, city, founders, entity_type
FROM manufacturers;

DROP TABLE manufacturers;
ALTER TABLE manufacturers_new RENAME TO manufacturers;

CREATE INDEX manufacturers_entity_type ON manufacturers (entity_type);

COMMIT;

PRAGMA foreign_keys = ON;
