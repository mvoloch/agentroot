"""Machine identity that came along when an agent home was copied from another computer.

Copying a user profile to a new machine copies more than projects and sessions. Two things in it
name the machine they were created on, and they keep naming the old one on the new machine:

    ~/.codex/state_<N>.sqlite  remote_control_enrollments(server_id, server_name, ...)
        The registration the Codex/ChatGPT desktop app uses for remote control. A copied row makes
        the new machine connect as the old one (same server_id, the old server_name), so both
        machines share one device entry and the phone, the ChatGPT agent and the web see one name.

    %LOCALAPPDATA%\\Packages\\OpenAI.Codex_*\\LocalCache
        The Microsoft Store app's own data (Electron profile, cookies, device state). Copied there,
        it keeps presenting the machine to the ChatGPT agent under the old name, even after the
        enrollment above is fixed. Only resetting the app (Reset-AppxPackage) clears it.

A copied file keeps its modification time but gets a new creation time, so a file modified
before it was created on this disk was copied from somewhere else.

`check` only reads. `fix` deletes copied enrollment rows (the app enrolls again under this
machine's name on its next start), after backing the database up. It never resets an app.
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re
import shutil
import socket
import sqlite3
from dataclasses import dataclass

from agentroot.adapters.util import env_dir
from agentroot.snapshot import columns, has_table, open_copy

# Store packages whose LocalCache holds an agent app's machine-bound state.
STORE_PACKAGES = ("OpenAI.Codex_*",)
# A file modified more than this long before it was created here was copied in.
COPY_SLACK = dt.timedelta(days=1)
# Only files the running app writes. Resources it installs (extensions, dictionaries, models)
# keep their build dates, so on a fresh install they also look "modified before created".
STATE_FILES = {"Local State", "Preferences", "Secure Preferences", "Cookies", "Login Data", "Web Data",
               "Network Persistent State", "TransportSecurity", "DIPS", "SharedStorage", "Trust Tokens"}
STATE_DIRS = {"leveldb", "IndexedDB", "Session Storage"}


@dataclass
class Finding:
    kind: str  # "enrollment" or "store-data"
    path: str
    detail: str
    fix: str


def hostname() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname().split(".")[0]


def _codex_state_dbs(user_home: str) -> list[str]:
    codex = env_dir(user_home, "CODEX_HOME", ".codex")
    out = []
    for folder in (codex, os.path.join(codex, "sqlite")):
        out += [f for f in glob.glob(os.path.join(folder, "state_*.sqlite")) if re.search(r"state_\d+\.sqlite$", f)]
    return out


def _enrollments(db: str) -> list[tuple[str, str]]:
    """(server_id, server_name) of every remote-control enrollment in a Codex state database."""
    with open_copy(db) as con:
        if not has_table(con, "remote_control_enrollments"):
            return []
        cols = columns(con, "remote_control_enrollments")
        if "server_name" not in cols:
            return []
        sid = "server_id" if "server_id" in cols else "''"
        return [(str(a or ""), str(b or "")) for a, b in con.execute(f"select {sid}, server_name from remote_control_enrollments")]


def _created(st: os.stat_result) -> float:
    return getattr(st, "st_birthtime", st.st_ctime)


def _copied_files(root: str) -> tuple[int, int, float]:
    """(files, files modified before they were created here, oldest such mtime)."""
    total = copied = 0
    oldest = 0.0
    for dirpath, _, files in os.walk(root):
        in_state_dir = bool(STATE_DIRS & set(dirpath.split(os.sep)))
        for f in files:
            if not in_state_dir and f not in STATE_FILES:
                continue
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            total += 1
            if dt.timedelta(seconds=_created(st) - st.st_mtime) > COPY_SLACK:
                copied += 1
                oldest = st.st_mtime if not oldest else min(oldest, st.st_mtime)
    return total, copied, oldest


def check(user_home: str, host: str | None = None) -> list[Finding]:
    host = host or hostname()
    out: list[Finding] = []
    for db in _codex_state_dbs(user_home):
        for server_id, name in _enrollments(db):
            if name.casefold() != host.casefold():
                out.append(Finding(
                    "enrollment", db,
                    f'remote control is enrolled as "{name}" ({server_id or "no server id"}), but this machine is "{host}"',
                    "close the app, then `agentroot identity --fix`; it enrolls again as this machine on its next start"))
    # creation times only mean "created here" on Windows
    if os.name == "nt":
        local = env_dir(user_home, "LOCALAPPDATA", "AppData", "Local")
        for pattern in STORE_PACKAGES:
            for pkg in glob.glob(os.path.join(local, "Packages", pattern)):
                cache = os.path.join(pkg, "LocalCache")
                total, copied, oldest = _copied_files(cache) if os.path.isdir(cache) else (0, 0, 0.0)
                if copied:
                    since = dt.datetime.fromtimestamp(oldest).date().isoformat()
                    name = os.path.basename(pkg).split("_")[0]
                    out.append(Finding(
                        "store-data", cache,
                        f"{copied} of {total} files were copied from another machine (modified before they were created here, oldest {since})",
                        f"close the app, run `Get-AppxPackage -Name {name} | Reset-AppxPackage`, sign in again and "
                        "re-allow any agent that uses this computer (this clears the app's local data, not ~/.codex)"))
    return out


def fix(user_home: str, host: str | None = None) -> list[str]:
    """Delete enrollment rows that name another machine. Returns what was done, one line each."""
    host = host or hostname()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    done = []
    for db in _codex_state_dbs(user_home):
        stale = [sid for sid, name in _enrollments(db) if name.casefold() != host.casefold()]
        if not stale:
            continue
        backup = os.path.join(user_home, ".agentroot", "identity-backup", stamp)
        os.makedirs(backup, exist_ok=True)
        prefix = os.path.basename(os.path.dirname(db)) + "-"
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db + suffix):
                shutil.copy2(db + suffix, os.path.join(backup, prefix + os.path.basename(db) + suffix))
        con = sqlite3.connect(db)
        try:
            n = con.execute("delete from remote_control_enrollments where lower(server_name) <> lower(?)", (host,)).rowcount
            con.commit()
            ok = con.execute("pragma quick_check").fetchone()[0]
        finally:
            con.close()
        if ok != "ok":
            raise RuntimeError(f"{db}: quick_check failed after the delete ({ok}); the backup is in {backup}")
        done.append(f"{db}: removed {n} enrollment(s) of another machine (backup in {backup})")
    return done
