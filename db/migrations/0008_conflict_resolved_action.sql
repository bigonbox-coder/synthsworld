-- Widen manufacturer_review_log.action's CHECK constraint to allow
-- 'conflict_resolved', alongside the existing approve/note/logo actions.
--
-- When the pipeline flags a manufacturer as needs_review because two sources
-- disagree, and Kristóf then settles which reading is right (or that the two
-- readings were never in conflict at all), that decision needs its own audit
-- trail entry: it is not an 'approved' click and not a free-form 'note_added',
-- it is a resolution that also moves the record's confidence_level. The note
-- field records what was decided and why, and the matching evidence goes into
-- facts_sources with source_tier 'owner' (see 0007_owner_source_tier.sql).
--
-- First case, 2026-08-30: Siel's 1986 vs 1987 end date, where the two years
-- turned out to describe two different events (operational end vs legal
-- deregistration) rather than two conflicting accounts of one.
--
-- SQLite can't ALTER a CHECK constraint in place -- same recreate-table
-- pattern as 0003 and 0006.
BEGIN TRANSACTION;

CREATE TABLE manufacturer_review_log_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  action TEXT NOT NULL CHECK (action IN (
    'approved', 'unapproved', 'note_added',
    'logo_approved', 'logo_outdated', 'logo_wrong',
    'conflict_resolved'
  )),
  note TEXT,
  previous_confidence_level TEXT,
  new_confidence_level TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO manufacturer_review_log_new
  (id, manufacturer_id, action, note, previous_confidence_level, new_confidence_level, created_at)
  SELECT id, manufacturer_id, action, note, previous_confidence_level, new_confidence_level, created_at
  FROM manufacturer_review_log;

DROP TABLE manufacturer_review_log;
ALTER TABLE manufacturer_review_log_new RENAME TO manufacturer_review_log;

COMMIT;
