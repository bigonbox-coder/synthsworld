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
if [ "$REFRESH" = "1" ]; then
  python3 db/probe_domains.py --top 20 2>&1 | sed 's/^/  domain:  /'
fi

python3 db/harvest_synfo.py   --ingest 2>&1 | tail -3 | sed 's/^/  synfo:   /'
python3 db/harvest_synthxl.py --ingest 2>&1 | tail -3 | sed 's/^/  synthxl: /'
python3 db/relink_manuals.py  --apply  2>&1 | tail -2 | sed 's/^/  relink:  /'

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

log "harvest kesz"
