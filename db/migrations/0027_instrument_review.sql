-- Hangszer-szintu ellenorzendo jelzes.
--
-- Kristof, 2026-09-02: "A halott forrast ugyanugy, mint a rovid gyartoval."
--
-- A rovid gyartonevek eseten (synth-db: ARP, Buchla, E-mu, ...) a script NEM
-- dontott, hanem a discovery_queue sort needs_review-ra tette es rairta miert.
-- Ugyanez kell hangszer-szinten is, mert a synth-db sitemapjaban 165 olyan cim
-- all, amire az oldal maga azt valaszolja: "No such synth :-(". A 2026-09-02-i
-- beemelesbol 36 hangszerunk EPPEN ilyen halott oldalra hivatkozik forraskent.
--
-- Ezek NAGYRESZT letezo hangszerek (Alesis QS6.1, Arturia MicroBrute SE), tehat
-- torolni oket hiba lenne. De a forrasuk semmit nem igazol, es van kozottuk
-- sitemap-szemet is. Ez emberi dontes, nem scripte.
--
-- A discovery_queue.status mintajara:
--   review_status = 'needs_review'  -> az adminban megjelolve, ember dont
--   review_note   = miert, sajat szavaval, hogy a dontes ne igenyeljen nyomozast
-- NULL a normalis allapot, tehat a meglevo 2173 sorbol egy sem valtozik.

ALTER TABLE instruments ADD COLUMN review_status TEXT;
ALTER TABLE instruments ADD COLUMN review_note TEXT;
