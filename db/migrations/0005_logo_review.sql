-- Logo review workflow (Kristóf, 2026-08-30). Reversible, three states:
-- NULL/unset = not yet reviewed, 'approved', 'outdated', 'wrong'.
-- Plain nullable column, no CHECK constraint -- Python-side validation is
-- enough, mirrors how long_history was added as a plain column earlier.
ALTER TABLE manufacturer_logos ADD COLUMN logo_review_status TEXT;
