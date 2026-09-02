-- Varolista-sorrend: melyik nevre menjen el a napi kutatasi kor eloszor.
--
-- Kristof, 2026-09-02, arra a felajanlasra hogy az ures csonk-gyartokat
-- soroljam elore: "Ok."
--
-- A csonkok azok a cegek, akik ugy kerultek a tablaba, hogy egy masik gyarto
-- kutatasa MEGEMLITETTE oket (rokoncegkent), de rajuk magukra soha nem ment
-- kutatas. Huszonegy ilyen van. Kezenfekvo lenne mind a huszonegyet elore
-- venni, csakhogy a huszonegy NEM egyforma, es ezt maga az adat mondja meg.
--
-- A kapcsolat TIPUSA arulja el, mit csinal az a ceg:
--   collaboration, successor, supplier, merged_with
--       -> maga is hangszereket vagy alkatreszt keszit (Mutable Instruments,
--          Noise Engineering, Paia, Fatar, Echolette). Ezek erdemesek a korre.
--   acquired_by, acquired, part_of, subsidiary_of, owner_of, sold_brand_to
--       -> tulajdonos, holding, kereskedo vagy akveziciós szereplo (Robert
--          Bosch, Triton Partners, Keenfinity, Telex, Guitar Center, Gibson).
--          Ezek csak KONTEXTUSKENT letezenek a tablaban, hogy egy felvasarlas
--          tortenete elmondhato legyen. Rajuk kort kolteni palyateveszes.
--
-- Ezert nem toroljuk es nem is soroljuk elore mind a huszonegyet, hanem
-- rangsorolunk. A priority csak sorrend, semmit nem zar ki: a nullas sorok
-- ugyanugy kutathatok, csak nem elsokent.
--
-- priority: 1 = elore, 0 = normal (alapertelmezes)

ALTER TABLE discovery_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_discovery_queue_priority
  ON discovery_queue (status, priority DESC);
