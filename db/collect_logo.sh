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
# Some hosts (WordPress behind a WAF, e.g. 360systems.com 2026-09-03) answer a
# UA-less curl with an HTML challenge page instead of the image, and the script
# then died with "Unrecognized file type" on a URL that is perfectly fine in a
# browser. Send a normal browser UA so the image comes back as an image.
curl -sL -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" -o "$RAW" "$URL"
TYPE="$(file -b "$RAW")"
case "$TYPE" in
  *SVG*)
    mv "$RAW" "/tmp/synthlogos/${BASE}.svg"
    echo "SVG, no resize needed: /tmp/synthlogos/${BASE}.svg"
    ;;
  *PNG*|*JPEG*|*JPG*|*GIF*)
    # GIF is converted to PNG, never kept: 2026-09-02 the Echolette wordmark
    # (300x93 GIF, echolette.com) was dropped as "unrecognized file type"
    # because only PNG/JPEG/SVG were listed here. A logo in GIF is old but
    # perfectly usable, and the admin serves PNG anyway.
    EXT="png"; case "$TYPE" in *JPEG*|*JPG*) EXT="jpg" ;; esac
    if [ "${TYPE#*GIF}" != "$TYPE" ]; then
      OUT="/tmp/synthlogos/${BASE}.png"
      # -frames:v 1 and an explicit rgba pixel format are BOTH needed: a GIF is
      # paletted (pal8) and may hold several frames, and without these ffmpeg
      # answers -22 (Invalid argument) instead of writing the file.
      ffmpeg -y -loglevel error -i "$RAW" -frames:v 1 \
        -vf "scale='min(2000,iw)':'min(2000,ih)':force_original_aspect_ratio=decrease,format=rgba" "$OUT"
      rm -f "$RAW"
      echo "GIF converted to PNG: $OUT"
      exit 0
    fi
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
