-- Melyik forráshoz VAN már leszedő, és melyikhez kell.
--
-- Kristóf, 2026-09-01: "Ha kell leszedő szkript azt mutasd az adminon (mihez,
-- mennyi) és a leszedőszkriptnél vedd figyelembe hogy ne oldalanként legyen
-- hanem optimalizált amit te is javasoltál."
--
-- Az első fele ez az oszlop: NULL azt jelenti, hogy a domain mérés szerint
-- feldolgozható, de még nincs aki leszedje. Az admin ebből csinál munkalistát,
-- a mennyiséget pedig a már meglévő product_urls adja -- így a lista magától
-- fontossági sorrendben áll.
--
-- A második fele nem adatbázis-kérdés, de ide írom, mert itt fog elromlani, ha
-- elromlik. A `harvester` érték NEM a domain neve lesz, hanem a CSALÁDÉ. A
-- Casio és a Yamaha ugyanaz a minta: sitemap, benne termékcímek, a kategória az
-- útvonalban. Ezekhez EGY leszedő kell, forrásonként egy beállítással, nem
-- kettő darab majdnem egyforma script.
--
-- Ez önkritika is: a synfo és a synthxl leszedője nyolcvan százalékban ugyanaz,
-- és külön születtek meg, mert a második írásakor még nem látszott a család.
-- Ezért kapnak most külön nevet: ami ma van, azt nem hazudom közösnek.
BEGIN TRANSACTION;

ALTER TABLE source_domains ADD COLUMN harvester TEXT;

CREATE INDEX source_domains_harvester ON source_domains (harvester);

UPDATE source_domains SET harvester = 'harvest_synfo'   WHERE domain = 'synfo.nl';
UPDATE source_domains SET harvester = 'harvest_synthxl' WHERE domain = 'synthxl.com';

COMMIT;
