-- Muszaki adatok a hangszerekhez, forrasonkent.
--
-- Kristof, 2026-09-03: "mehet a leszedo" -- az emumania.net kb. 45 E-mu gephez
-- ad ugyanolyan adatlap-tablazatot (billentyuszam, ROM-meret, preset-szamok,
-- szolamszam, effektek, kimenetek). Eddig nem volt hova tenni oket: a
-- review_note gepi jegyzet, nem adatmezo, es egy prozai mondatbol nem lehet
-- kesobb szurni vagy osszehasonlitani.
--
-- MIERT KULCS-ERTEK, ES NEM FIX OSZLOPOK
-- ======================================
-- Mert meg nem tudjuk, mi a vegleges mezolista, es egy korai fix sema rossz
-- helyre szegezne le. Egy dobgepnek nincs billentyuszama, egy modularis
-- rendszernek nincs presetje, egy 2001-es workstationnek van CD-ROM-olvasoja.
-- Kulcs-ertekkel minden forras azt adja at, amit tud, es a vegleges
-- megjelenites kesobb valogat belole. Ha egyszer allandosul a lista, abbol
-- lehet nezetet vagy oszlopokat csinalni -- forditva nem menne.
--
-- A source_url a sorban all, nem kulon tablaban, es a UNIQUE is tartalmazza:
-- KET FORRAS MONDHAT MAST ugyanarra a mezore, es ez nem hiba, hanem
-- informacio. Az ellentmondas igy latszik, nem elveszik.
--
-- Az ertek NYERSEN tarolodik, ahogy a forras irja ("4MB", "32 Voices",
-- "192 (64 RAM, 128 ROM)"). A normalizalas kesobbi lepes, es visszafele nem
-- lehetne kitalalni, mit dobtunk el.

CREATE TABLE IF NOT EXISTS instrument_specs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
  field         TEXT NOT NULL,   -- rom_size, presets, polyphony, keys, ...
  label         TEXT,            -- a forras sajat felirata, ahogy o hivja
  value         TEXT NOT NULL,   -- nyers ertek, ahogy a forras mondja
  source_url    TEXT NOT NULL,
  source_name   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (instrument_id, field, source_url)
);

CREATE INDEX IF NOT EXISTS idx_instrument_specs_instrument
  ON instrument_specs(instrument_id);
CREATE INDEX IF NOT EXISTS idx_instrument_specs_field
  ON instrument_specs(field);
