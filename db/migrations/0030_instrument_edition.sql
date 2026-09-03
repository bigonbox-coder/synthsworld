-- Ujrakiadas: ugyanaz a nev, mas termek.
--
-- Kristof, 2026-09-03: "az is nehezseg, hogy a retro divat miatt sok hangszert
-- kiadtak ujra vagy ugyanazon a neven maskent. pl Arp Axxe az eredeti, de
-- kiadta a Korg is nemrég, vagy Korg MS10, amit kiadtak ugyanazon a neven de
-- az mar egy kontroller szoftveres tamogatassal. Termeszetesen ezek kulon
-- termekek tehat kulon is kezeljuk."
--
-- A regi sema ezt NEM engedte: UNIQUE (manufacturer_id, name). Ket Korg MS-10
-- (az 1978-as szintetizator es a mai kontroller) egyszeruen nem fert el
-- egymas mellett, a masodik beszuras csendben eldobodott vagy felulirta az
-- elsot. A kulonbozo gyartotol szarmazo eset (ARP Axxe kontra a Korg-fele
-- kiadas) mukodott, mert mas a manufacturer_id -- csak epp semmi nem kotötte
-- ossze a kettot.
--
-- Ket uj mezo:
--   edition        rovid megkulonbozteto. Alapertek 'original', tehat a
--                  meglevo 2608 sor viselkedese valtozatlan. Nyitott lista,
--                  mint a category. Hasznalt ertekek:
--                    original    az elso, eredeti kiadas
--                    reissue     kesobbi ujrakiadas (sajat vagy jogutod marka)
--                    clone       mas ceg masolata/tisztelgese (Behringer)
--                    controller  azonos nev, de mar vezerlo, nem hangkelto
--                    software    azonos nev pluginkent
--                    kit         epitokeszlet-valtozat
--   reissue_of_id  melyik sort eleszti ujra. Gyartokon ATIVELHET, ez a lenyege:
--                  a Korg-fele Axxe sora az ARP Axxe sorara mutat.
--
-- Az UNIQUE innentol (manufacturer_id, name, edition), tehat a duplikatum-vedelem
-- megmarad, de a valodi kulon termek elfer. Az edition NOT NULL, szandekosan:
-- NULL-lal a SQLite minden sort egyedinek latna, es pont a vedelem veszne el.
--
-- FONTOS a kutatasnak: egy ujrakiadas eve NEM az eredeti eve. Ha egy sorban
-- 2015-os evszam all egy 1974-es hangszernel, az nem elirás, hanem osszemosott
-- ket termek. Ezert kapott a ket Moog modularis rendszer kulon eredeti sort.

PRAGMA foreign_keys = OFF;

CREATE TABLE instruments_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
  name TEXT NOT NULL,
  year INTEGER,
  category TEXT,
  source_url TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  technology TEXT NOT NULL DEFAULT 'unknown'
    CHECK (technology IN ('analog', 'digital', 'hybrid', 'unknown')),
  review_status TEXT,
  review_note TEXT,
  edition TEXT NOT NULL DEFAULT 'original',
  edition_note TEXT,
  reissue_of_id INTEGER REFERENCES instruments(id),
  UNIQUE (manufacturer_id, name, edition)
);

INSERT INTO instruments_new
  (id, manufacturer_id, name, year, category, source_url, created_at,
   technology, review_status, review_note)
SELECT id, manufacturer_id, name, year, category, source_url, created_at,
       technology, review_status, review_note
FROM instruments;

DROP TABLE instruments;
ALTER TABLE instruments_new RENAME TO instruments;

CREATE INDEX idx_instruments_manufacturer ON instruments(manufacturer_id);
CREATE INDEX instruments_technology ON instruments (technology);
CREATE INDEX idx_instruments_reissue_of ON instruments(reissue_of_id);
CREATE INDEX idx_instruments_edition ON instruments(edition) WHERE edition <> 'original';

PRAGMA foreign_keys = ON;

-- A ket megmert eset. A retrosynthads meres talalta oket: a rogzitett evszam
-- ujabb, mint a hirdetes, mert a rogzitett ev az UJRAKIADASE.
--   System 35 -- nalunk 2015 volt, kozben ott a hatoldalas brosura 1974-bol
--   System 55 -- nalunk 2016 volt, kozben ott az 1980-as Moog arlista
-- A meglevo sor marad az ujrakiadas (az evszama arra igaz), es melle kerul az
-- eredeti. Az eredeti eve szandekosan URES: a hirdetes eve felso becsles, nem
-- megjelenesi datum (lasd derivation_rule_proposals #4, elutasitva).

UPDATE instruments SET
  edition = 'reissue',
  edition_note = 'A Moog 2015-ben ujragyartotta az eredeti modularis rendszert. Az evszam erre a kiadasra igaz.'
WHERE id = 2545;

UPDATE instruments SET
  edition = 'reissue',
  edition_note = 'A Moog 2016-ban ujragyartotta az eredeti modularis rendszert. Az evszam erre a kiadasra igaz.'
WHERE id = 2546;

INSERT INTO instruments (manufacturer_id, name, year, category, technology,
                         edition, edition_note, review_status, review_note)
SELECT manufacturer_id, name, NULL, category, technology, 'original',
       'Az eredeti, 1970-es evekbeli modularis rendszer. Kulon sor, mert az ujrakiadas (2015) mas termek.',
       'needs_review',
       'Evszam nelkul. Bizonyitek: hatoldalas Moog brosura 1974-bol es az 1980. junius 28-i Moog arlista (retrosynthads), tehat 1974-ben MAR letezett. A pontos megjelenesi ev kutatando.'
FROM instruments WHERE id = 2545;

INSERT INTO instruments (manufacturer_id, name, year, category, technology,
                         edition, edition_note, review_status, review_note)
SELECT manufacturer_id, name, NULL, category, technology, 'original',
       'Az eredeti, 1970-es evekbeli modularis rendszer. Kulon sor, mert az ujrakiadas (2016) mas termek.',
       'needs_review',
       'Evszam nelkul. Bizonyitek: az 1980. junius 28-i Moog arlista es az 1982-es Moog katalogus (retrosynthads), tehat 1980-ban MAR letezett. A pontos megjelenesi ev kutatando.'
FROM instruments WHERE id = 2546;

UPDATE instruments SET reissue_of_id =
  (SELECT id FROM instruments o WHERE o.manufacturer_id = instruments.manufacturer_id
     AND o.name = instruments.name AND o.edition = 'original')
WHERE id IN (2545, 2546);

-- A korabeli hirdetesek az EREDETI termeket hirdetik, nem a 2015-os ujrakiadast.
UPDATE external_links SET instrument_id =
  (SELECT o.id FROM instruments o JOIN instruments r ON r.id = external_links.instrument_id
    WHERE o.manufacturer_id = r.manufacturer_id AND o.name = r.name AND o.edition = 'original')
WHERE instrument_id IN (2545, 2546)
  AND domain = 'retrosynthads.blogspot.com';
