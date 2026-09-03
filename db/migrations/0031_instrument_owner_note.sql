-- Harmadik valasz a hangszer-jelolesekre: a gazda megjegyzese.
--
-- Kristof, 2026-09-03: "akkor szerintem tegyel mindegyikhez egy opciot hogy
-- megjegyzes es oda beirom hogy mi a helyzet vele."
--
-- Eddig ket gomb volt, Marad es Torles, es mind a ketto VEGLEGES iteletet
-- kert olyan sorokrol, ahol epp az a helyzet, hogy nem tudni eleget. A
-- harmadik valasz az, amikor Kristof tud valamit, amit a forrasok nem
-- mondanak meg: hogy ket kulon termekrol van szo, hogy a nev elirás, hogy a
-- gep letezik de mas neven fut. Ez nem dontes a sorrol, hanem ADAT a
-- sorhoz, es utana a munka megint az enyem.
--
--   owner_note      amit Kristof beirt, valtozatlanul. Nem keverjuk a
--                   review_note-ba: az gepi eredetu jegyzet, ez emberi
--                   allitas, es a kettot kesobb is meg kell tudni
--                   kulonboztetni.
--   owner_note_at   mikor irta.
--
-- A review_status uj erteket kap: 'owner_answered'. Ezzel a sor lekerul
-- Kristof listajarol (valaszolt ra), de nem tunik el: a hangszer-dontesek
-- lapon kulon szakaszban all, mint ami RAM var. A mezonek nincs CHECK
-- constrainte, tehat ehhez nem kell semat bontani.

ALTER TABLE instruments ADD COLUMN owner_note TEXT;
ALTER TABLE instruments ADD COLUMN owner_note_at TEXT;

CREATE INDEX IF NOT EXISTS idx_instruments_owner_note
  ON instruments(review_status) WHERE owner_note IS NOT NULL;
