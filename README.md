# Synthsworld

Folyamatosan bővülő adatbázis szintetizátor-gyártókról és hangszereikről.
Kristóf személyes/félig-magánprojektje, később synthsworld.com néven
weboldalként jelenik meg. Külön áll a marveen fleet repótól.

## Fázisok

1. **Gyártók** (ebben az állapotban) -- cégadatok, névtörténet, kapcsolatok
   (felvásárlás/beolvadás), logók, forrás-hivatkozott tények.
2. Hangszerek gyártókhoz kapcsolva (még nincs megépítve).
3. Dokumentumok/fájlok (kézikönyv, firmware, hirdetés stb., forrás + méret +
   oldalszám + kategória + 1-5 minőségi besorolás) (még nincs megépítve).
4. Nyilvános weboldal ugyanerre az adatbázisra építve (még nincs megépítve).

## Adatbázis

SQLite fájl: `db/synthsworld.sqlite`. Séma: `db/migrations/*.sql`,
additív migrációkkal (soha nem törlünk/írunk át meglévő táblát, csak
bővítünk). Migráció alkalmazása:

```
python3 db/migrations/apply.py
```

Minden automata futtatás előtt a DB-ről mentés készül
(`db/backups/<timestamp>.sqlite`), lásd a
`.claude/skills/synthsworld-manufacturer-discovery/SKILL.md` eljárást.

### Táblák (1. fázis)

- `manufacturers` -- egy sor/gyártó, kanonikus névvel, országgal, rövid
  történettel, hivatalos weboldallal, állapottal (aktív/megszűnt/felvásárolt)
  és megbízhatósági szinttel.
- `manufacturer_name_history` -- egy gyártóhoz tetszőlegesen sok
  névváltozás (ugyanaz a cég, más név, mettől-meddig).
- `manufacturer_relations` -- KÉT KÜLÖN gyártó közti kapcsolat
  (felvásárolta / beolvadt / kivált belőle), évszámmal.
- `manufacturer_logos` -- logók évkörrel, Drive-linkkel (2. fázistól
  töltődik ténylegesen).
- `facts_sources` -- minden kinyert tény forrás-hivatkozással, forrás-
  rangsorral (hivatalos oldal / Wikidata / egyéb). Ütköző forrásoknál
  MINDKÉT érték megmarad, nincs csendes döntés.
- `discovery_queue` -- munkasor: melyik gyártót kell (még) kutatni, milyen
  státuszban tart (found / company_info_done / needs_review / done).

## Kutatási/bővítési folyamat

Nincs önjáró, LLM nélküli scraper -- a tényleges kutatás (webes keresés,
oldal-lekérés a `quarantine-reader` biztonsági mintán keresztül, forrás-
ütközés eldöntése) ágens-vezérelt lépés. Lásd a skill fájlt:
`.claude/skills/synthsworld-manufacturer-discovery/SKILL.md`.

Jelenleg NINCS ütemezett feladathoz kötve -- Kristóf először élesben, együtt
teszteli le néhány valódi gyártón, mielőtt a folyamatos automatikus bővítés
bekapcsolna.

## Kezdő teszt-köteg

A `discovery_queue` fel van töltve 8 ismert gyártóval (Moog, Roland, Korg,
Sequential, Yamaha, Oberheim, ARP Instruments, Elektron) `found` státusszal,
DE a tényleges kutatás még NEM futott le rajtuk. Ez az első élő teszt
köteg -- lásd a skill fájl eljárását az elindításához.

Újratöltés (idempotens, duplikátumot nem hoz létre):

```
python3 db/seed_queue.py
```
