#!/usr/bin/env bash
# Deploy site/ to synthsworld.com over FTPS.
#
# Resolves the password from the marveen vault entry "FTP - Synthsworld" and
# hands it to deploy.py through the environment, so the secret never reaches
# the command line, a file in this repo, or the shell history.
set -euo pipefail

MARVEEN="${MARVEEN_DIR:-$HOME/marveen}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--dry-run" ]]; then
  exec python3 "$HERE/deploy.py" --dry-run
fi

# The vault entry stores the password followed by a plain-language note about
# the host and user; the password is the first whitespace-delimited token.
secret="$(echo "FTPSECRET=FTP - Synthsworld" \
  | node "$MARVEEN/scripts/vault-resolve.mjs" \
  | sed -n 's/^FTPSECRET=//p')"

if [[ -z "$secret" ]]; then
  echo "could not resolve the vault entry 'FTP - Synthsworld'" >&2
  exit 2
fi

SYNTHSWORLD_FTP_PASSWORD="${secret%%[[:space:]]*}" \
  python3 "$HERE/deploy.py" "$@"
