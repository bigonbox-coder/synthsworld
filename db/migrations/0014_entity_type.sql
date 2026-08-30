-- manufacturers.entity_type: 'company' or 'individual'.
--
-- Kristóf's decision (2026-08-30 06:11): individual builders worth keeping
-- should live IN the database for later -- many of them made genuinely good
-- instruments -- but they must not clutter the manufacturer review list in the
-- admin panel right now.
--
-- A separate table would fork every query, every relation and every instrument
-- link for what is one attribute of the same kind of entity: something that
-- made an instrument. One column, defaulted to 'company', keeps the whole
-- pipeline unchanged and makes hiding them a WHERE clause.
--
-- This is NOT the same question as the scope rule. Whether a person belongs in
-- the database at all is decided by the finished-product test in the discovery
-- skill; entity_type only records what a kept record IS.
BEGIN TRANSACTION;

ALTER TABLE manufacturers ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'company'
  CHECK (entity_type IN ('company', 'individual'));

CREATE INDEX manufacturers_entity_type ON manufacturers (entity_type);

COMMIT;
