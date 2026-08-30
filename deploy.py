#!/usr/bin/env python3
"""Upload site/ to the Synthsworld web host over explicit FTPS.

The password is NOT stored here. It comes from the marveen vault entry
"FTP - Synthsworld", either already in $SYNTHSWORLD_FTP_PASSWORD or resolved
on the fly by deploy.sh. Everything else is non-secret configuration.

Usage:  ./deploy.sh            upload every file under site/
        ./deploy.sh --dry-run  list what would be uploaded, connect to nothing
"""

import os
import sys
from ftplib import FTP_TLS
from pathlib import Path

HOST = "ftp.konline.hu"
PORT = 21
USER = "jarvis@synthsworld.com"
LOCAL = Path(__file__).resolve().parent / "site"
# The FTP account is chrooted to its own home, which maps to the site root.
REMOTE = "."
SKIP = {"__pycache__", ".DS_Store", "generate.py"}


def files():
    for path in sorted(LOCAL.rglob("*")):
        if path.is_dir() or any(part in SKIP for part in path.parts):
            continue
        yield path, path.relative_to(LOCAL)


def ensure_dir(ftp, rel_dir):
    """mkd each level; an existing directory is not an error."""
    parts = [p for p in rel_dir.parts if p not in (".", "")]
    ftp.cwd(REMOTE)
    for part in parts:
        try:
            ftp.mkd(part)
        except Exception:
            pass
        ftp.cwd(part)


def main():
    dry = "--dry-run" in sys.argv
    plan = list(files())
    if not plan:
        print(f"nothing to upload under {LOCAL}", file=sys.stderr)
        return 1
    if dry:
        for _, rel in plan:
            print(f"would upload {rel}")
        print(f"-- dry run, {len(plan)} files, no connection made --")
        return 0

    password = os.environ.get("SYNTHSWORLD_FTP_PASSWORD")
    if not password:
        print("SYNTHSWORLD_FTP_PASSWORD is not set -- run ./deploy.sh, not this "
              "script directly", file=sys.stderr)
        return 2

    ftp = FTP_TLS()
    ftp.connect(HOST, PORT, timeout=60)
    ftp.login(USER, password)
    ftp.prot_p()                      # encrypt the data channel too, not just auth
    try:
        for path, rel in plan:
            ensure_dir(ftp, rel.parent)
            with path.open("rb") as fh:
                ftp.storbinary(f"STOR {rel.name}", fh)
            print(f"uploaded {rel} ({path.stat().st_size} bytes)")
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    print(f"done, {len(plan)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
