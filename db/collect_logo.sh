#!/usr/bin/env bash
# Download one manufacturer logo file from a known URL, cap it at 2000px on
# the long edge if it's a raster image (never upscale), and leave it ready
# for upload. Does NOT touch Drive or the database itself -- those steps
# need the Agent tool (mcp__google-drive__*) and sqlite3, which this plain
# shell script can't reach. This just handles the "get the file, resize if
# needed" mechanical part so a future research pass doesn't have to
# reinvent the ffmpeg incantation.
#
# Usage: collect_logo.sh <logo-url> <output-basename-no-ext>
# Writes to /tmp/synthlogos/<output-basename>.<ext>
set -euo pipefail
URL="${1:?usage: collect_logo.sh <url> <output-basename>}"
BASE="${2:?usage: collect_logo.sh <url> <output-basename>}"
mkdir -p /tmp/synthlogos
RAW="/tmp/synthlogos/${BASE}.raw"
curl -sL -o "$RAW" "$URL"
TYPE="$(file -b "$RAW")"
case "$TYPE" in
  *SVG*)
    mv "$RAW" "/tmp/synthlogos/${BASE}.svg"
    echo "SVG, no resize needed: /tmp/synthlogos/${BASE}.svg"
    ;;
  *PNG*|*JPEG*|*JPG*)
    EXT="png"; case "$TYPE" in *JPEG*|*JPG*) EXT="jpg" ;; esac
    OUT="/tmp/synthlogos/${BASE}.${EXT}"
    # Scale down only if either dimension exceeds 2000px; force_original_aspect_ratio
    # keeps proportions; this never upscales a small logo (min() with the source size).
    ffmpeg -y -loglevel error -i "$RAW" -vf "scale='min(2000,iw)':'min(2000,ih)':force_original_aspect_ratio=decrease" "$OUT"
    rm -f "$RAW"
    echo "Raster, resized if needed: $OUT"
    ;;
  *)
    echo "Unrecognized file type for $URL: $TYPE" >&2
    rm -f "$RAW"
    exit 1
    ;;
esac
