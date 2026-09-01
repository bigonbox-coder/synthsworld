-- Kristóf kategória-rendszere: két tengely + a technológia külön.
--
-- Az ő megfogalmazása (2026-09-01): "Keyboard - Synthesizer, Keyboard - Piano,
-- Keyboard - Workstation, Keyboard - Midi ... ezeknél a keyboard arra utal, hogy
-- billentyűs a kialakítása, a másik pedig hogy szintetizátor, vagy workstation
-- szintetizátor, vagy Midi, ami csak egy midi billentyűzet hangkeltés nélkül,
-- vagy pl Keyboard - Arranger ami kísérőautomatikás szintetizátor. Hasonlóan
-- Module - Synthesizer, Module - Arranger, Keyboard - Sampler, Module - Sampler."
--
-- A NÉV összetett, a TÁROLÁS nem. A `Keyboard - Synthesizer` pontosan az a
-- címke, amit ő kért, és úgy is jelenik meg. De ha CSAK szövegként tárolnánk,
-- visszakapnánk a szorzótáblát, amiből az imént jöttünk ki: minden új forma
-- megszorozza az összes funkciót, és a "mutasd az összes samplert, formától
-- függetlenül" kérdésre nem lehetne válaszolni. Ezért a `form` és a `function`
-- külön oszlop, a `name` pedig a kettő olvasható alakja.
--
-- A TECHNOLÓGIA nem kategória, hanem a hangszer tulajdonsága, ezért az
-- instruments táblába kerül, nem a categories-be. Ugyanaz a hangszer lehet
-- `Keyboard - Synthesizer` és analóg is; a kettő független. Kristóf példái:
-- Yamaha SK30 analóg, Roland W-30 digitális, és "lehetnek olyanok ahol már
-- keveredett a technológia" -- ezért van `hybrid`.
--
-- Az alapérték `unknown`, nem `analog`. Ugyanaz az elv, mint a manufacturers
-- .status-nál a 0017-ben: a hallgatás nem bizonyíték, és 1546 hangszerről ma
-- nem tudjuk. Egy alapértelmezés, ami állítást tesz, hazugsággá válik a sorok
-- 90 százalékán.
--
-- A meglévő 122 kategória `form` és `function` mezője NULL marad. Azok
-- besorolása Kristóf taxonómiai munkája; egy migráció nem találhatja ki
-- helyette, hogy a `V-Drums` melyik tengelyre esik.
BEGIN TRANSACTION;

ALTER TABLE categories ADD COLUMN form TEXT;
ALTER TABLE categories ADD COLUMN function TEXT;

CREATE INDEX categories_form ON categories (form);
CREATE INDEX categories_function ON categories (function);

ALTER TABLE instruments ADD COLUMN technology TEXT NOT NULL DEFAULT 'unknown'
  CHECK (technology IN ('analog', 'digital', 'hybrid', 'unknown'));

CREATE INDEX instruments_technology ON instruments (technology);

-- Kristóf alapkészlete, szó szerint ahogy felsorolta. Ő maga írta, hogy "nem
-- teljes, csak alapok", tehát ez kezdőkészlet és nem zárt lista.
INSERT OR IGNORE INTO categories (name, form, function, note) VALUES
  ('Keyboard - Synthesizer', 'Keyboard', 'Synthesizer', 'Kristóf alapkészlete, 2026-09-01'),
  ('Keyboard - Piano',       'Keyboard', 'Piano',       'Kristóf alapkészlete, 2026-09-01'),
  ('Keyboard - Workstation', 'Keyboard', 'Workstation', 'Kristóf alapkészlete, 2026-09-01'),
  ('Keyboard - MIDI',        'Keyboard', 'MIDI',        'Vezérlő hangkeltés nélkül. Kristóf alapkészlete, 2026-09-01'),
  ('Keyboard - Arranger',    'Keyboard', 'Arranger',    'Kísérőautomatikás. Kristóf alapkészlete, 2026-09-01'),
  ('Keyboard - Sampler',     'Keyboard', 'Sampler',     'Kristóf alapkészlete, 2026-09-01'),
  ('Module - Synthesizer',   'Module',   'Synthesizer', 'Kristóf alapkészlete, 2026-09-01'),
  ('Module - Arranger',      'Module',   'Arranger',    'Kísérőautomatikás hangmodul. Kristóf alapkészlete, 2026-09-01'),
  ('Module - Sampler',       'Module',   'Sampler',     'Kristóf alapkészlete, 2026-09-01');

COMMIT;
