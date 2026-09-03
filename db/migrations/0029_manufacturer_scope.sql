-- Scope-jelzes a gyarto-rekordokon.
--
-- Kristof, 2026-09-03: a fooldali "Kikutatatlan" csempe 16-ot mutatott, es
-- rakerdezett, miert nem fogy. A valasz az volt, hogy abbol a 16-bol csak
-- HAROM valodi kutatasi jelolt (Gibson, Hillwood, VEB Klingenthaler). A tobbi
-- 13 sor relaciobol keletkezett csonk: tulajdonos, felvasarlo, befektetesi
-- alap, kereskedo vagy akusztikus hangszergyarto. Ezek soha nem lesznek
-- megerositett elektronikus hangszergyartok, mert nem azok. Amig egy kalap ala
-- estek a valodi jeloltekkel, a csempe orokre tizenharom nem letezo munkat
-- hirdetett.
--
-- A rekordokat NEM toroljuk. Ket okbol: a relaciok masik vege rajuk mutat
-- (a Wurlitzer 1909-es felvasarlasanak kell egy North Tonawanda sor), es
-- torles utan az ingest.py a kovetkezo relacio-emlitesnel neman ujra
-- letrehozna ugyanezt a csonkot. Ehelyett megjeloljuk oket.
--
-- A scope NEM a confidence_level erteke lett, mert a ketto mas kerdesre valaszol:
--   confidence_level = mennyire tudjuk, amit tudunk (kutatasi allapot)
--   scope            = egyaltalan ide tartozik-e (besorolasi dontes)
-- Egy out_of_scope sor allhat unresearched szinten orokre, az nem hianyossag.
--
-- Az uj sorok alapertelmezese 'in_scope', tehat a meglevo viselkedes nem valtozik,
-- es az ingest.py stubjai is valodi jeloltkent szuletnek tovabbra is.

ALTER TABLE manufacturers ADD COLUMN scope TEXT NOT NULL DEFAULT 'in_scope'
  CHECK (scope IN ('in_scope', 'out_of_scope'));
ALTER TABLE manufacturers ADD COLUMN scope_note TEXT;

UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Hangszerbolt-lanc, nem gyarto. A Simmons markat vasarolta meg 2005-ben.'
  WHERE canonical_name = 'Guitar Center';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Mechanikus vasari orgonak es zenegepek gyara, elektronikus hangszert nem keszitett. A Wurlitzer 1909-ben vasarolta fel.'
  WHERE canonical_name = 'North Tonawanda Barrel Organ Factory';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Akusztikus zongorat es onjatszo zongorat gyartott. A Wurlitzer 1919-ben vasarolta fel.'
  WHERE canonical_name = 'Melville Clark Piano Company';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Akusztikus fuvos hangszereket gyartott. A Wurlitzer 1964-ben vasarolta fel.'
  WHERE canonical_name LIKE 'Henry C. Martin Band Instrument%';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'A Wurlitzer nemet jukebox-leanyvallalata. Jukebox = lejatszogep, nem hangkelto hangszer.'
  WHERE canonical_name = 'Deutsche Wurlitzer GmbH';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Jukebox-gyarto (Leeds, UK). Kristof megerositette 2026-09-03: hangszert nem gyartottak.'
  WHERE canonical_name = 'Sound Leisure';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Holding, a Hohner tulajdonosa volt 1989-tol. Maga nem gyart hangszert.'
  WHERE canonical_name LIKE 'Kunz-Holding%';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Tajvani hangszerkonszern (Jupiter fuvosok), a Hohner tulajdonosa 1997-tol. Akusztikus profil.'
  WHERE canonical_name LIKE 'KHS Musical Instruments%';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Hiradastechnikai cegcsoport, a Dynacord felvasarloja 1990-ben. Nem hangszergyarto.'
  WHERE canonical_name = 'Telex Communications';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Ipari konszern, a Dynacord tulajdonosa 2006-tol. Nem hangszergyarto.'
  WHERE canonical_name = 'Robert Bosch GmbH';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'Magantoke-befekteto alap, a Dynacord uzletagat vette meg 2025-ben. Nem hangszergyarto.'
  WHERE canonical_name = 'Triton Partners';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'A Triton alatt letrejott cegcsoport, ide tartozik 2025-tol a Dynacord. Nem hangszergyarto.'
  WHERE canonical_name = 'Keenfinity Group';
UPDATE manufacturers SET scope = 'out_of_scope', scope_note =
  'A Dean Guitars anyavallalata, tole vette meg a Clavia 2005-ben a Ddrum markat. Gitargyarto profil.'
  WHERE canonical_name = 'Armadillo Enterprises';
