#!/usr/bin/env python3
"""Reachability check for external_links.

Most of these URLs were written between 1998 and 2012. Treating them as
sources without checking would mean citing pages that have not existed for
fifteen years. A dead link is not worthless either -- it is exactly what the
Wayback Machine is for -- but it must be labelled as dead.

HEAD first (cheap), GET on the servers that refuse HEAD. Redirects are
followed and the landing URL recorded, because a redirect to a corporate
front page is not the same as the page still being there.

Usage:
  python3 db/check_links.py                 # everything still 'unchecked'
  python3 db/check_links.py --recheck dead  # re-test one status
  python3 db/check_links.py --type manufacturer_official
"""

import argparse
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "synthsworld.sqlite"
# A plain bot UA gets 403'd by every Cloudflare-fronted host, which would
# label live sources dead. Present as a real browser; anything that still
# refuses is recorded as 'blocked', not 'error'.
UA = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
WORKERS = 12
TIMEOUT = 15

_host_lock = threading.Lock()
_host_last = {}


def pace(host, gap=1.0):
    """No more than one request per second per host."""
    while True:
        with _host_lock:
            now = time.time()
            last = _host_last.get(host, 0.0)
            if now - last >= gap:
                _host_last[host] = now
                return
            wait = gap - (now - last)
        time.sleep(wait)


class HeadRequest(urllib.request.Request):
    def get_method(self):
        return "HEAD"


def check(url, domain):
    pace(domain)
    for req_cls in (HeadRequest, urllib.request.Request):
        try:
            req = req_cls(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                final = r.geturl()
                status = "redirected" if final.rstrip("/") != url.rstrip("/") else "live"
                return status, r.status, final
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 501) and req_cls is HeadRequest:
                continue                      # server dislikes HEAD, retry as GET
            if e.code in (404, 410):
                return "dead", e.code, None
            # 401/402/403/451 = the host answered and refused us; that is a
            # live server, not a broken link.
            if e.code in (401, 402, 403, 451):
                return "blocked", e.code, None
            return "error", e.code, None
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            dead = any(s in str(reason).lower() for s in
                       ("name or service not known", "nodename nor servname",
                        "no address associated", "name resolution"))
            return ("dead" if dead else "error"), None, None
    return "error", None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recheck", help="re-test rows with this status instead")
    ap.add_argument("--type", help="limit to one link_type")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    sql = "SELECT id, url, domain FROM external_links WHERE status = ?"
    params = [args.recheck or "unchecked"]
    if args.type:
        sql += " AND link_type = ?"
        params.append(args.type)
    sql += " ORDER BY id"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    rows = conn.execute(sql, params).fetchall()
    print(f"{len(rows)} links to check", file=sys.stderr)

    results = []
    lock = threading.Lock()

    def one(row):
        rid, url, domain = row
        status, code, final = check(url, domain)
        with lock:
            results.append((status, code, final, rid))
            if len(results) % 100 == 0:
                print(f"  {len(results)}/{len(rows)}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, rows))

    with conn:
        conn.executemany(
            """UPDATE external_links
               SET status = ?, http_status = ?, final_url = ?,
                   checked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id = ?""", results)

    for status, n in conn.execute(
            "SELECT status, COUNT(*) FROM external_links GROUP BY 1 ORDER BY 2 DESC"):
        print(f"{status:12} {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
