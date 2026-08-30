-- Add a fourth source_tier: 'owner'.
--
-- Some facts get settled by Kristóf directly rather than by a web source --
-- either from his own knowledge or from research he did himself. The first
-- case (2026-08-30) was Siel: two sources gave 1986 and 1987 for the end of
-- the company and the pipeline flagged them as conflicting, when in fact they
-- describe two different events (production stop plus insolvency in 1986; legal
-- deregistration and the registration of Roland Europe S.p.A. in 1987).
--
-- Such a resolution still belongs in facts_sources -- every stored fact must
-- carry its provenance -- but it is neither a manufacturer's own site, nor
-- Wikidata, nor a random web source, and burying it under 'other' would hide
-- that it outranks everything else on the record. The source_url for these
-- rows takes the form 'owner-review:kristof/YYYY-MM-DD'.
--
-- Tier precedence when picking a display value becomes:
--   owner > manufacturer_official > wikidata > other
--
-- SQLite can't ALTER a CHECK constraint in place, so this is the same
-- recreate-table pattern as 0003. Migrations stay additive-only: this file is
-- new, the earlier ones are untouched.

PRAGMA foreign_keys=OFF;

CREATE TABLE facts_sources_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  field_name TEXT NOT NULL, -- e.g. 'short_history', 'country', 'founding_year'
  value TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_tier TEXT NOT NULL CHECK (source_tier IN ('owner', 'manufacturer_official', 'wikidata', 'other')),
  fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO facts_sources_new (id, manufacturer_id, field_name, value, source_url, source_tier, fetched_at)
  SELECT id, manufacturer_id, field_name, value, source_url, source_tier, fetched_at FROM facts_sources;

DROP TABLE facts_sources;
ALTER TABLE facts_sources_new RENAME TO facts_sources;

PRAGMA foreign_keys=ON;
