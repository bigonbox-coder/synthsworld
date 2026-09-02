-- Szabály-javaslatok: ami elemzés közben feltűnik, ne vesszen el.
--
-- Kristóf, 2026-09-02: "ha elemző, AI használat során felmerül olyan
-- összefüggés amit érdemes beépíteni a kereső scriptbe, akkor azt jelezd és
-- akkor döntünk. Fontos, hogy a keresőscript folyamatosan automatikusan
-- fejlődjön. (Akkor is ha meg kell erősítenem néha)"
--
-- A levezetett tények rétege (0022) megvan, de eddig egyetlen módon bővült:
-- ha én kézzel eszembe jutott. Egy észrevétel, ami egy kutatási kör közben
-- születik, a kör végén elveszett. Ez a tábla az a hely, ahova azonnal
-- lekerül, még a döntés előtt.
--
-- A folyamat szándékosan kétlépcsős. A JAVASLAT automatikus: aki kutat, az
-- felírja, amit észrevett, és mellé teszi a bizonyítékot. A BEVEZETÉS nem
-- automatikus: Kristóf dönt róla, mert egy rossz levezetési szabály nem egy
-- rekordot ront el, hanem az összes olyat, amire illik.
--
-- status: proposed -> approved | rejected | implemented
--   proposed     felírva, döntésre vár
--   approved     mehet, de a kód még nincs meg
--   implemented  a szabály bekerült a derive_facts.py RULES listájába
--   rejected     megnéztük, nem jó, és a note megmondja miért (ez is érték,
--                mert megakadályozza, hogy fél év múlva újra felvessük)

CREATE TABLE IF NOT EXISTS derivation_rule_proposals (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_name    TEXT NOT NULL UNIQUE,
  description  TEXT NOT NULL,
  evidence     TEXT,
  affects      TEXT,
  status       TEXT NOT NULL DEFAULT 'proposed',
  note         TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  decided_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule_proposals_status
  ON derivation_rule_proposals (status);
