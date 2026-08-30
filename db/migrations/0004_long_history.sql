-- Add a longer, more detailed history alongside the existing short_history.
-- Both are kept -- short_history stays the brief default, long_history is
-- an optional ~3x-longer expansion. Plain ALTER TABLE ADD COLUMN: no CHECK
-- constraint involved, so no table-recreate needed (unlike 0003).
ALTER TABLE manufacturers ADD COLUMN long_history TEXT;
