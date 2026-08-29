-- Synthsworld phase 1: manufacturers.
-- Migrations are ADDITIVE ONLY. Never edit an applied migration file --
-- add a new numbered one instead. See db/migrations/apply.py.

CREATE TABLE IF NOT EXISTS manufacturers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT NOT NULL UNIQUE,
  country TEXT,
  short_history TEXT,
  official_website TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'defunct', 'acquired')),
  confidence_level TEXT NOT NULL DEFAULT 'needs_review' CHECK (confidence_level IN ('confirmed', 'needs_review')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- A manufacturer can rename itself any number of times and stay the SAME
-- entity -- unlimited rows here per manufacturer_id. Distinct from
-- manufacturer_relations, which links TWO DIFFERENT manufacturer records.
CREATE TABLE IF NOT EXISTS manufacturer_name_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  name TEXT NOT NULL,
  start_year INTEGER,
  end_year INTEGER
);

-- Relation between two DIFFERENT manufacturer records (acquisition, merger,
-- spin-off). relation_type stays free text on purpose -- the category list
-- may grow and this must never require a schema migration to add one.
CREATE TABLE IF NOT EXISTS manufacturer_relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  related_manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  relation_type TEXT NOT NULL, -- e.g. 'acquired_by' | 'merged_into' | 'spun_off_from' -- open list
  year INTEGER
);

CREATE TABLE IF NOT EXISTS manufacturer_logos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  drive_file_url TEXT, -- left null in phase 1; no Drive upload step yet
  start_year INTEGER,
  end_year INTEGER
);

-- Generic source citation for every extracted fact. Multiple rows per
-- (manufacturer_id, field_name) are EXPECTED when sources disagree -- never
-- overwrite in place, always append, and let the confidence logic decide
-- whether the manufacturer counts as confirmed or needs_review.
CREATE TABLE IF NOT EXISTS facts_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  field_name TEXT NOT NULL, -- e.g. 'short_history', 'country', 'founding_year'
  value TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_tier TEXT NOT NULL CHECK (source_tier IN ('manufacturer_official', 'wikidata', 'other')),
  fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- The phase-1 work queue. A processing pass walks 'found' rows, researches
-- each, and advances status. Batch size is chosen by whoever runs a pass,
-- not encoded here.
CREATE TABLE IF NOT EXISTS discovery_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_name TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'found' CHECK (status IN ('found', 'company_info_done', 'needs_review', 'done')),
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
