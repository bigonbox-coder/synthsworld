-- Synthsworld phase 1 add-on: reversible approve/unapprove + freeform notes.
-- Migrations are ADDITIVE ONLY. Never edit an applied migration file --
-- add a new numbered one instead. See db/migrations/apply.py.
--
-- The "current" state stays on manufacturers.confidence_level (already
-- exists, unchanged). This table is the audit trail: every approve,
-- unapprove, and note is logged here, which is what makes an approval
-- reversible and explainable rather than a silent one-way edit.
CREATE TABLE IF NOT EXISTS manufacturer_review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  action TEXT NOT NULL CHECK (action IN ('approved', 'unapproved', 'note_added')),
  note TEXT,
  previous_confidence_level TEXT,
  new_confidence_level TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
