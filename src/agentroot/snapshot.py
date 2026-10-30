"""Open an agent's SQLite database without touching it.

The agents keep these databases open in WAL mode. Opening them in place, even read-only,
can create -shm files or contend for locks with the running app. So we copy the database
together with its -wal and -shm to a private temp dir and read the copy.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator


@contextlib.contextmanager
def open_copy(db_path: str) -> Iterator[sqlite3.Connection]:
    tmp = tempfile.mkdtemp(prefix="agentroot-")
    try:
        dst = os.path.join(tmp, os.path.basename(db_path))
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                shutil.copy2(db_path + suffix, dst + suffix)
        con = sqlite3.connect(dst)
        try:
            yield con
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'pragma table_info("{table}")')]


def has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone() is not None
