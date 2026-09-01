-- Egy hangszer több kategóriába tartozhat.
--
-- Kristóf döntése (2026-09-01): "Egy konkrét hangszer lehet több kategóriában
-- is. Pl van olyan orgona ami három manuálos, az első egy analóg szintetizátor,
-- a másik kettő pedig egy orgona. Általában nem sok kategóriába megy egy
-- hangszer, de pár lehet."
--
-- És a szabály, ami miatt ez nem fajul el -- ez a fontosabb fele. Egy kategória
-- akkor kerül a hangszerre, ha MEGHATÁROZÓ rá nézve, nem akkor, ha a funkció
-- pusztán jelen van. Az ő példája: a Korg Trinity workstation. Van benne
-- szekvenszer, némelyikben sampler is, de egyik sem meghatározó, tehát azokat a
-- kategóriákat NEM kapja meg. A háromsoros orgona viszont tényleg orgona is és
-- szintetizátor is, mert az egyik manuál valóban analóg szintetizátor.
--
-- Ha ez a szabály elvész, minden workstation megkap négy kategóriát, és a
-- kategória mező pontosan annyit fog érni, mint a szabad szöveg, amit lecserél.
--
-- Az `instruments.category` oszlop MARAD, az elsődleges kategória tükreként.
-- Az admin/server.py és a site/generate.py ma abból olvas; egy migráció nem jó
-- alkalom arra, hogy két másik programot is átírjunk. Az új igazságforrás a
-- join tábla, a tükör onnan tartható karban.
--
-- A `categories` külön tábla, nem csak szabad szöveg a join táblában: így egy
-- kategória átnevezése EGY sor módosítása lesz, nem 1546 hangszeré. A jelenlegi
-- 122 szöveg rendbetétele pont ezért lesz olcsóbb, mint amilyen ma volna.
BEGIN TRANSACTION;

CREATE TABLE categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE instrument_categories (
  instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
  PRIMARY KEY (instrument_id, category_id)
);

CREATE INDEX instrument_categories_category ON instrument_categories (category_id);

INSERT INTO categories (name)
  SELECT DISTINCT TRIM(category) FROM instruments
  WHERE category IS NOT NULL AND TRIM(category) <> '';

INSERT INTO instrument_categories (instrument_id, category_id, is_primary)
  SELECT i.id, c.id, 1
  FROM instruments i
  JOIN categories c ON c.name = TRIM(i.category)
  WHERE i.category IS NOT NULL AND TRIM(i.category) <> '';

COMMIT;
