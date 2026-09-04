-- Levezetett hangszer-tenyek provenanciaja.
--
-- Kristof, 2026-09-04: "kitoltheted ami igazolt." Ez a tabla teszi
-- visszavonhatova azt, amit egy szabaly a hangszer-sorokba ir.
--
-- MIERT KELL UJ TABLA
-- ===================
-- A facts_sources csak gyartokat ismer (manufacturer_id NOT NULL). A
-- derive_facts.py egesz kerete arra epult, es a WRITABLE_FIELDS is a
-- manufacturers oszlopait sorolja. A hangszer-szintu levezeteshez ugyanaz a
-- garancia kell, ami a gyartoknal mar megvan: a derived_from mezobol
-- kiderul, MELYIK szabaly es MILYEN bemenet adta az erteket, tehat egy rossz
-- szabaly teljes termese egyetlen DELETE-tel azonosithato es visszavonhato.
--
-- Az elso hasznaloja a technology_from_oscillators szabaly: az
-- instrument_specs 'oscillators' mezojenek nyers szovegebol olvassa ki, hogy
-- a forras kimondja-e a "Digital"/"VCO" szot. Ez NEM kovetkeztetes: a mert
-- 95 ellenorzo eseten 100 szazalek volt az egyezes es nulla a tevedes, es a
-- szabaly hallgat (nem ir semmit) a 103 olyan esetben, ahol a szoveg nem
-- mondja ki. A meres a kod mellett all, a szabaly docstringjeben.

CREATE TABLE IF NOT EXISTS instrument_facts_sources (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
  field_name    TEXT NOT NULL,   -- technology, year, category, ...
  value         TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  source_tier   TEXT NOT NULL CHECK (source_tier IN ('owner', 'manufacturer_official', 'wikidata', 'other')),
  fetched_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  derived_from  TEXT             -- a szabaly neve + a bemenet, ha levezetes
);

CREATE INDEX IF NOT EXISTS idx_instrument_facts_sources_instrument
  ON instrument_facts_sources(instrument_id);
CREATE INDEX IF NOT EXISTS idx_instrument_facts_sources_derived
  ON instrument_facts_sources(derived_from);
