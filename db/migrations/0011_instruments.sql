-- Instrument NAMES per manufacturer. Names only, deliberately.
--
-- Kristóf's call (2026-08-30): a model list is cheap to collect during the same
-- research pass that covers the company, and it earns its place twice over --
-- it shows what the company actually built, which is how the scope rule gets
-- decided, and model names surface manufacturers we had never heard of. The
-- full instrument table with specifications is phase 2 and is NOT this.
--
-- year is the first release year where a source states it, NULL otherwise: the
-- same rule as the company columns, never guessed.

CREATE TABLE instruments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  name TEXT NOT NULL,
  year INTEGER,
  category TEXT,            -- synthesizer / drum machine / organ / ... open list
  source_url TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (manufacturer_id, name)
);

CREATE INDEX idx_instruments_manufacturer ON instruments(manufacturer_id);
