#!/usr/bin/env python3
"""Apply pending .sql migrations in this directory, in filename order.

Idempotent: tracks applied filenames in a schema_migrations table, so
re-running only applies what's new. Migrations are additive-only by
convention -- never edit an already-applied file, add a new numbered one.

Usage: python3 db/migrations/apply.py [path-to-sqlite-file]
Defaults to db/synthsworld.sqlite relative to the project root.
"""
import sqlite3
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent
DEFAULT_DB = MIGRATIONS_DIR.parent / "synthsworld.sqlite"


def apply_migrations(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ")"
    )
    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
    pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in applied)
    if not pending:
        print(f"Up to date, no pending migrations ({db_path}).")
        return
    for path in pending:
        sql = path.read_text()
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
        conn.commit()
        print(f"Applied {path.name}")
    conn.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    apply_migrations(target)
