-- Levezetett tények: amit nem mondott ki a forrás, de gépiesen következik.
--
-- Kristóf, 2026-09-02, a Steiner-Parker rekord kapcsán: "nem tudjuk az
-- országot, ahol készült. De tudjuk, hogy Salt Lake City, ami ugye simán
-- meghatározható, hogy Amerika. Tehát valahogyan azt kellene kialakítani,
-- hogy ez a keresési script folyamatosan tudjon fejlődni, okosodni."
--
-- Igaza van, és eddig ez a lehetőség nem létezett: a kiolvasó szigorú
-- szabálya az, hogy CSAK azt írja le, amit a forrás kimond, különben a
-- modell elkezd kitalálni. Ez a szabály jó, és marad. A hiányzó darab az
-- volt, hogy a kimondott tényekből utólag, GÉPIESEN is lehessen továbbjutni.
--
-- Ezért válik szét most két dolog, amit eddig egy kalap alatt tároltunk:
--   1. amit a forrás KIMONDOTT (derived_from IS NULL), és
--   2. amit egy nevesített szabály VEZETETT LE belőle (derived_from kitöltve).
--
-- A levezetett ténynek ugyanúgy van forrás-URL-je, mert a levezetés maga sem
-- a modell fejéből jön: a város-ország szabály a Wikidatát kérdezi meg, tehát
-- a végeredmény hivatkozható. A derived_from mező azt mondja meg, MELYIK
-- szabály és MILYEN bemenet adta, hogy később bármikor felül lehessen
-- vizsgálni vagy vissza lehessen vonni egy egész szabály termését.
--
-- Formátum: "<szabaly_neve>: <bemeneti mezo>=<bemeneti ertek>"
-- Példa:    "city_to_country: city=Salt Lake City"

ALTER TABLE facts_sources ADD COLUMN derived_from TEXT;

CREATE INDEX IF NOT EXISTS idx_facts_sources_derived
    ON facts_sources (derived_from)
    WHERE derived_from IS NOT NULL;
