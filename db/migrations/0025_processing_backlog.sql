-- Feldolgozasi varolista: ami penzbe kerul, az legyen felirva, ne a fejemben.
--
-- Kristof, 2026-09-02: "A szintiket, gyartokat beemelheted, ami koltseg a
-- kiolvasashoz azt valahogy jegyezzuk, hogy majd kesobb tudjuk utemezni, de
-- az is kelleni fog."
--
-- A projekt kettevalasztja a gyujtest es a feldolgozast (lasd a "tokenhasznalo
-- feldolgozas elott szolj" szabalyt). A gyujtes ingyen skalazodik, a
-- feldolgozas nem. Eddig viszont a "majd kesobb" sehol nem volt felirva:
-- ha egy forrasbol csak a nevek jottek be, es a tobbi modellmunkat igenyelt
-- volna, az az igeny elveszett a beszelgetessel egyutt.
--
-- Ez a tabla az a hely, ahol egy elhalasztott feldolgozas all, MERT
-- MEGMERVE, hogy kesobb utemezheto legyen, es hogy latszodjon, mennyibe
-- kerulne. A becslest mindig meressel toltjuk ki, nem erzesre: hany egyseg
-- (oldal, rekord), es egy egyseg mekkora.
--
-- status: pending -> scheduled -> running -> done | dropped

CREATE TABLE IF NOT EXISTS processing_backlog (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_name      TEXT NOT NULL UNIQUE,
  description   TEXT NOT NULL,
  source_domain TEXT,
  unit_kind     TEXT,              -- mi az egyseg: "oldal", "rekord", "kep"
  unit_count    INTEGER,           -- hany egyseg
  bytes_per_unit INTEGER,          -- MERT atlagos szoveghossz egysegenkent
  est_tokens    INTEGER,           -- ebbol szamolt becsult token, be + ki
  prerequisite  TEXT,              -- mi kell hozza elotte (pl. oldal-cache)
  yields        TEXT,              -- mit adna, ha lefutna
  status        TEXT NOT NULL DEFAULT 'pending',
  note          TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_processing_backlog_status
  ON processing_backlog (status);
