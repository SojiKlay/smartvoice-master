"""Consistent snapshot of the SmartVoice SQLite database.

Copying the .db file while the app is writing can capture a half-written
page. This uses SQLite's online backup API from a read-only connection, checks
the copy with ``PRAGMA integrity_check`` and only then gives it its final
name, so a file named ``smartvoice-*.db`` in the backup folder is always usable.

Usage:
    python scripts/backup_db.py [--db data/smartvoice.db] [--out data/backups] [--keep 14]

Prints the path of the new snapshot. The deploy script's backup job uploads the
folder to S3; restoring is described in deploy/aws-ec2/README.md.
Snapshots hold customer data — keep them out of Git (data/ is ignored).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "smartvoice-"
SUFFIX = ".db"


def backup(db_path: str | Path, out_dir: str | Path, now: datetime | None = None) -> Path:
    """Write a checked snapshot of ``db_path`` into ``out_dir`` and return its path."""
    source_path = Path(db_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"database not found: {source_path}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    final = out / f"{PREFIX}{stamp}{SUFFIX}"
    partial = out / f"{PREFIX}{stamp}{SUFFIX}.partial"
    partial.unlink(missing_ok=True)

    # Read-only: a backup must never be able to change the live database.
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        target = sqlite3.connect(partial)
        try:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            target.close()
    finally:
        source.close()

    if result != "ok":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"integrity check failed on the snapshot: {result}")
    os.replace(partial, final)
    return final


def prune(out_dir: str | Path, keep: int) -> list[Path]:
    """Delete the oldest snapshots beyond ``keep``; return what was removed."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    snapshots = sorted(Path(out_dir).glob(f"{PREFIX}*{SUFFIX}"))
    removed = snapshots[:-keep] if len(snapshots) > keep else []
    for path in removed:
        path.unlink()
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/smartvoice.db"))
    parser.add_argument("--out", default="data/backups")
    parser.add_argument("--keep", type=int, default=14, help="local snapshots to keep (default 14)")
    args = parser.parse_args(argv)
    try:
        path = backup(args.db, args.out)
        prune(args.out, args.keep)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
