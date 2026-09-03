#!/usr/bin/env bash
# Rendszeres, modell nelkuli gyujtes.
#
# Kristof, 2026-09-01: "alapbol futtathatjuk rendszeresen a scriptet, ez 0
# tokenhasznalat." Pontosan. Ez a runner az, ami ezt megcsinalja magatol.
#
# Amit csinal, es amit NEM. Csak gyujt: uj linkeket es uj modellneveket hoz be
# a szerkezetes forrasokbol, es ujraparositja a manualokat a kozben letrejott
# hangszerekkel. NEM ir tortenetet, NEM dont scope-kerdest, NEM allapit meg
# evszamot -- azokhoz olvasni kell, az a modell dolga. Amit ez a script talal,
# az JELOLT, nem adat.
#
# A kulso oldalakat csak a --refresh kapcsoloval kerdezi meg ujra (heti egyszer
# eleg; a synfo egy hobbi-szerver, ne verjuk). Nelkule a gyorsitotarbol dolgozik,
# es akkor a futas teljesen halozat-mentes.
set -uo pipefail
cd "$(dirname "$0")/.."

REFRESH=0
[ "${1:-}" = "--refresh" ] && REFRESH=1

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

log "harvest indul (refresh=$REFRESH)"

if [ "$REFRESH" = "1" ]; then
  # A gyorsitotar urítese kell ahhoz, hogy az UJ modelleket egyaltalan meglassa;
  # a fetch amugy kihagyja a mar letoltott fajlokat.
  rm -f db/cache/synfo-servicemanuals.html
  rm -rf db/cache/synthxl
  python3 db/harvest_synfo.py --fetch   2>&1 | sed 's/^/  synfo:   /'
  python3 db/harvest_synthxl.py --fetch 2>&1 | tail -3 | sed 's/^/  synthxl: /'
fi

# Heti korben megmerunk nehany meg nem vizsgalt forras-domaint. Csak a
# refresh-korben, mert ez kulso oldalakat kerdez; huszan bosegesen eleg, a sor
# a sajat linkgrafunk szorasa szerint all.
# Forras-meres. 2026-09-03-ig csak a heti korben futott, husszal. Kozben
# kiderult, hogy 274 domain volt MEG SOSEM megmerve, tehat a szuk keresztmetszet
# nem a leszedes, hanem a meretlen forras. Ezert most MINDEN nap megy negyven,
# es a heti kor is marad. Halozat, nulla modellhasznalat.
python3 db/probe_domains.py --top 40 2>&1 | tail -3 | sed 's/^/  domain:  /'

if [ "$REFRESH" = "1" ]; then
  # A Wikidata nem valtozik naponta, es a vegpont vendegszeretetet sem
  # illik heti egynel tobbszor igenybe venni.
  python3 db/harvest_wikidata.py --ingest 2>&1 | tail -2 | sed 's/^/  wikidata: /'
fi

# A gyartoi honlapok csaladja: egy leszedo, forrasonkent egy beallitassal.
python3 db/harvest_sitemap.py --all --ingest $([ "$REFRESH" = "1" ] && echo --refresh) 2>&1 | grep -E "^(yamaha|casio):" | sed 's/^/  sitemap: /'

python3 db/harvest_synfo.py   --ingest 2>&1 | tail -3 | sed 's/^/  synfo:   /'
python3 db/harvest_synthxl.py --ingest 2>&1 | tail -3 | sed 's/^/  synthxl: /'
python3 db/relink_manuals.py  --apply  2>&1 | tail -2 | sed 's/^/  relink:  /'

# INGYEN KOR (Kristof, 2026-09-03: "ami mar megbeszelt folyamat es nem
# tokenhasznalat, tehat valamilyen helyi scriptet futtat, az mehet magatol
# ejjel"). Mind a ot lepes helyi, nulla modellhasznalat, es mind idempotens:
# csak URES mezot tolt ki, meglevo adatot nem ir felul.
#   markanev-parok  -> hangszerek a mar letoltott synth-db cache-bol
#   spec-kiolvasas  -> evszam, kategoria, technologia ugyanabbol a cache-bol
#   levezetett teny -> pl. varosbol orszag, Wikidata-alapon
#   duplikatum      -> varolistas sorok jelolese, scope-on kivuliek lezarasa
#   halott forras   -> a nem letezo lapra mutato source_url levalasztasa
python3 db/import_synthdb_brands.py --apply 2>&1 | tail -2 | sed 's/^/  markapar: /'
python3 db/read_synthdb_specs.py    --ingest 2>&1 | tail -2 | sed 's/^/  specek:  /'
python3 db/derive_facts.py          --apply  2>&1 | tail -2 | sed 's/^/  levezet: /'
python3 db/queue_dupe_check.py      --apply  2>&1 | tail -2 | sed 's/^/  dupe:    /'
python3 db/detach_dead_sources.py   --apply  2>&1 | tail -2 | sed 's/^/  halott:  /'
python3 db/admin_freshness_check.py          2>&1 | sed 's/^/  admin:   /'

python3 - <<'PYEOF'
import sqlite3
c = sqlite3.connect('db/synthsworld.sqlite')
q = lambda s, *a: c.execute(s, a).fetchone()[0]
print("  allapot: "
      f"{q('select count(*) from manufacturers')} gyarto, "
      f"{q('select count(*) from instruments')} hangszer, "
      f"{q('select count(*) from external_links')} link, "
      f"{q('select count(*) from external_links where instrument_id is not null')} hangszerhez kotve, "
      f"{q('select count(*) from discovery_queue where status = ?', 'found')} a varolistan")
PYEOF

# A hozam maradjon meg. Az ejszakai kor kulonben masnap reggel piszkos
# munkafat hagy maga utan, es a kovetkezo commit belekeverne a sajat
# valtoztatasaiba. Kristof sajat repoja, a push elozetesen engedelyezett.
if [ -n "$(git status --porcelain)" ]; then
  SUM="$(python3 - <<'PYEOF'
import sqlite3
c = sqlite3.connect('db/synthsworld.sqlite')
q = lambda s, *a: c.execute(s, a).fetchone()[0]
print(f"{q('select count(*) from manufacturers')} gyarto, "
      f"{q('select count(*) from instruments')} hangszer "
      f"({q('select count(*) from instruments where year is not null')} evszammal), "
      f"{q('select count(*) from external_links')} link, "
      f"{q('select count(*) from discovery_queue where status = ?', 'found')} a varolistan, "
      f"{q('select count(*) from source_domains where verdict = ?', 'untested')} meretlen forras")
PYEOF
)"
  git add -A
  git commit -q -m "data: ejszakai ingyen kor -- $SUM"     -m "Automatikus futas (synthsworld-harvest.service), nulla modellhasznalat. Leszedes a szerkezetes forrasokbol, forras-meres, spec-kiolvasas a cache-bol, levezetett tenyek, duplikatum-szures. Amit ez a kor talal, az JELOLT, nem kimondott teny."
  git push -q 2>&1 | sed 's/^/  push:    /'
  log "hozam commitolva: $SUM"
else
  log "nem valtozott semmi, nincs commit"
fi

log "harvest kesz"
