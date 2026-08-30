-- Widen manufacturer_review_log.action's CHECK constraint to allow the new
-- logo-review actions (logo_approved/logo_outdated/logo_wrong), alongside
-- the existing approved/unapproved/note_added. SQLite can't ALTER a CHECK
-- constraint in place -- same recreate-table pattern as 0003_unresearched_state.sql.
BEGIN TRANSACTION;

CREATE TABLE manufacturer_review_log_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  action TEXT NOT NULL CHECK (action IN (
    'approved', 'unapproved', 'note_added',
    'logo_approved', 'logo_outdated', 'logo_wrong'
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
