-- Forrás-domainek nyilvántartása: mit próbáltunk, mi lett belőle, és MIÉRT.
--
-- Kristóf, 2026-09-01: "ha tudjuk azokat az oldalakat is jegyezzük meg ahol
-- jók, nagyok a találatok de valami miatt nem tudtuk leszedni. Ilyen pl a
-- modulos oldal is nem?"
--
-- Igen. És a tanulság az esti munkából: a "nem tudtuk leszedni" nem egyetlen
-- dolog. Három eset oldódott meg ma este, mindegyik azután, hogy kiderült az
-- OKA. A Casio HTML-jét botvédelem tiltja, de a sitemapot bárkinek kiadják. A
-- fandom lapjai 402-vel dobnak vissza, de az api.php nyitva van. A forat.com-on
-- nincs HTTPS, a lekérő meg mindent átír arra. Egyik megoldáshoz sem kellett
-- megkerülni semmit, csak a jó ajtón bemenni.
--
-- Ezért a `reason` mező a lényeg, nem a `verdict`. Egy tiltólista csak annyit
-- mondana, hogy "nem megy", és attól holnap ugyanúgy nekifutnánk. Az ok
-- megmondja, van-e út.
--
-- A `blocked_policy` külön kategória, és tiszteletben tartjuk. A ModularGrid
-- tiltja az AI-crawlereket: ott megállunk, és a `note` azt jegyzi fel, mi a
-- jogtiszta alternatíva. Ennek a sornak akkor is haszna van, ha sosem szedünk
-- le róla semmit: tudjuk hogy létezik, tudjuk mekkora, és ha egyszer engedélyt
-- kapunk, tudjuk mit nyerünk vele.
--
-- Gyakorlati haszon, amiért ez ma este megszületett: ha fel van jegyezve hogy
-- egy oldal miért nem ment, nem próbáljuk újra minden héten. A Wayback CDX-szel
-- ma öt perc ment el, mert sehol nem volt leírva, hogy nekünk 403-at ad.
BEGIN TRANSACTION;

CREATE TABLE source_domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL UNIQUE,
  verdict TEXT NOT NULL DEFAULT 'untested'
    CHECK (verdict IN (
      'untested',        -- még nem mértük
      'harvestable',     -- van sitemap vagy API, géppel feldolgozható
      'html_only',       -- csak HTML, elvileg megy, de drágább
      'blocked_bot',     -- botvédelem a HTML-en; KERESD a sitemapot/API-t
      'blocked_policy',  -- kifejezetten tiltja a gépi olvasást -- MEGÁLLUNK
      'transport',       -- szállítási gond (nincs HTTPS, TLS-hiba)
      'gone',            -- az oldal megszűnt
      'our_bug',         -- mi rontottuk el (rossz címformátum)
      'irrelevant'       -- él és elérhető, de nincs benne semmi nekünk
    )),
  reason TEXT,                    -- a KONKRÉT ok: HTTP-kód, hibaszöveg, mit láttunk
  route TEXT,                     -- ha van út: 'sitemap' | 'api' | 'http' | 'archive'
  route_url TEXT,                 -- a működő belépési pont
  robots_ok INTEGER,              -- a robots.txt engedi-e (1/0/NULL=nem tudjuk)
  sitemap_urls INTEGER,           -- hány cím a sitemapben
  product_urls INTEGER,           -- ebből hány néz ki termékoldalnak
  inbound_links INTEGER,          -- hány linkünk mutat rá (a saját linkgráfunkból)
  inbound_spread INTEGER,         -- HÁNY KÜLÖNBÖZŐ hangszerről -- ez a jó jel
  note TEXT,
  first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_checked TEXT
);

CREATE INDEX source_domains_verdict ON source_domains (verdict);

-- A saját linkgráfunk MÁR TUDJA, hová menjünk legközelebb. 255 domain, és a
-- szórás (hány KÜLÖNBÖZŐ hangszerről hivatkozunk rá) a jó jel: ami sok helyről
-- kap linket, az széles forrás, nem egy gyártó saját oldala.
INSERT INTO source_domains (domain, inbound_links, inbound_spread)
  SELECT domain, COUNT(*),
         COUNT(DISTINCT COALESCE(instrument_id, -manufacturer_id))
  FROM external_links
  WHERE domain IS NOT NULL AND TRIM(domain) <> ''
  GROUP BY domain;

COMMIT;
