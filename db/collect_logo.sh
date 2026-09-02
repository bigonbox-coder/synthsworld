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
    # Only re-encode when the image is ACTUALLY too big. A logo is almost always
    # well under 2000px, and running it through ffmpeg for nothing is both waste
    # and risk: 2026-09-02 a 645x122 yuvj444p jpeg (the Bontempi wordmark) made
    # ffmpeg fail with -22, so a perfectly good logo was dropped as "download
    # failed". Measure first, convert only if needed.
    W="$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$RAW" 2>/dev/null || echo 0)"
    H="$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$RAW" 2>/dev/null || echo 0)"
    if [ "${W:-0}" -le 2000 ] && [ "${H:-0}" -le 2000 ] && [ "${W:-0}" -gt 0 ]; then
      mv "$RAW" "$OUT"
      echo "Raster ${W}x${H}, no resize needed: $OUT"
    else
      # force_original_aspect_ratio keeps proportions; min() never upscales.
      ffmpeg -y -loglevel error -i "$RAW" -vf "scale='min(2000,iw)':'min(2000,ih)':force_original_aspect_ratio=decrease" "$OUT"
      rm -f "$RAW"
      echo "Raster ${W}x${H}, resized: $OUT"
    fi
    ;;
  *)
    echo "Unrecognized file type for $URL: $TYPE" >&2
    rm -f "$RAW"
    exit 1
    ;;
esac
