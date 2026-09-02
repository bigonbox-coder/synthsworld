-- Mikor szedtuk le TENYLEGESEN egy forrast.
--
-- Kristof, 2026-09-02: "a synth db-nek jelzi, hogy leszedo kell", majd
-- "Ne feledd az admin up to date legyen!"
--
-- Ket kulon allitas keveredett eddig egy mezoben. A source_domains.harvester
-- azt mondja meg, hogy VAN-E leszedonk hozza. Azt viszont sehol nem tartottuk
-- nyilvan, hogy le is FUTOTT-E. Emiatt a fooldal elorejelzese a mar feldolgozott
-- oldalakat is jovobeli hozamkent mutatta: 2026-09-02-en 9052 "megmert
-- termekoldal" allt ott (hu.yamaha.com 4912, www.casio.com 2237, synth-db.com
-- 1903), holott mind a harmat mar leszedtuk. Ez nem apro szepseghiba: pont az a
-- szam volt hamis, ami alapjan eldontjuk, hova erdemes menni.
--
-- Backfill: ahol van bizonyitek (tolunk szarmazo hangszer vagy kulso link az
-- adott domainrol), ott a LEGKESOBBI ilyen rekord ideje. Ez nem talalgatas,
-- hanem a sajat adatunkbol olvasott teny. Ahol nincs bizonyitek, marad NULL.

ALTER TABLE source_domains ADD COLUMN harvested_at TEXT;

UPDATE source_domains
   SET harvested_at = COALESCE(
       (SELECT MAX(i.created_at) FROM instruments i
         WHERE i.source_url LIKE '%' || source_domains.domain || '%'),
       (SELECT MAX(l.created_at) FROM external_links l
         WHERE l.domain = source_domains.domain))
 WHERE harvester IS NOT NULL;
