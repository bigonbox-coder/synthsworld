-- Termekcsalad es valtozat: egy tipus, tobb hangszer.
--
-- Kristof, 2026-09-03: "Termeszetesen minden kulon hangszert kulon kezelunk,
-- majd a vegleges weboldalon kitalalunk valami megjelenitest, hogy egy adott
-- tipusbol milyen variaciok voltak. Pl. Korg Trinity a tipus, a plus a
-- hosszabb billentyus valtozat, a prox a 88 billentyus kalapacsmechanikas, a
-- plus az amiben benne van a sample player opcio, a V3 amiben benne van a
-- moss bovito stb."
--
-- Ket kulon dolgot mond ki, es a sema eddig egyiket sem tudta:
--   1. minden valtozat KULON sor marad (ez mar all a 0030 ota),
--   2. de latszania kell, hogy egy TIPUSHOZ tartoznak, mert a weboldal igy
--      fogja mutatni oket.
--
-- Ezert nem eleg a nev prefixe. A "Trinity ProX" nevbol kitalalhato lenne a
-- csalad, a "TR-Rack"-bol nem, pedig ugyanaz a gep rack-formaban. Es
-- forditva: a "Proteus 2000" nevben ott a Proteus, de az mar a kesobbi
-- generacio. Nevbol nem lehet csoportositani, ezert kell egy explicit link.
--
--   instrument_families    a tipus: gyarto + nev + jegyzet. Nem hangszer-sor,
--                          mert a csalad neve nem mindig letezett termekkent.
--                          A Proteus pont ilyen: Kristof szerint a csalad
--                          neve volt, az elso gep a Proteus/1.
--   instruments.family_id  melyik tipushoz tartozik ez a sor
--   instruments.variant_label
--                          MI kulonbozteti meg a testvereitol, roviden, a
--                          weboldalnak: "88 billentyu, kalapacsmechanika",
--                          "rack valtozat", "MOSS bovitovel". A hosszu
--                          magyarazat marad a review_note-ban.
--
-- A csalad NEM ugyanaz, mint az ujrakiadas (0030). A Trinity ProX nem a
-- Trinity ujrakiadasa, hanem testvere. Egy sor lehet egyszerre csalad-tag es
-- ujrakiadas is: a Moog System 55 ujrakiadas 2016-bol a modularis csalad
-- tagja, es kozben az 1970-es eredetire mutat vissza.

CREATE TABLE IF NOT EXISTS instrument_families (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  name            TEXT NOT NULL,
  note            TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (manufacturer_id, name)
);

ALTER TABLE instruments ADD COLUMN family_id INTEGER REFERENCES instrument_families(id);
ALTER TABLE instruments ADD COLUMN variant_label TEXT;

CREATE INDEX IF NOT EXISTS idx_instruments_family ON instruments(family_id);
