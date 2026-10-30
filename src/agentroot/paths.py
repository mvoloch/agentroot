"""Path normalization.

Every agent records the same folder differently:

    Claude Code   C:\\Users\\me\\proj                  (and C:/Users/me/proj in ~/.claude.json)
    Codex         \\\\?\\C:\\Users\\me\\proj              (threads.cwd in state_5.sqlite)
    Antigravity   file:///c%3A/Users/me/proj         (workspace_uris)
    Gemini CLI    c:\\users\\me\\proj                    (lower-cased, projects.json)

`display()` turns any of them into a readable native path; `key()` turns it into the
value used to decide that two records point at the same folder.
"""
from __future__ import annotations

import ntpath
import os
import posixpath
import re
from urllib.parse import unquote, urlparse

_WIN_DRIVE = re.compile(r"^[A-Za-z]:")


def _is_windows_path(p: str) -> bool:
    return bool(_WIN_DRIVE.match(p)) or p.startswith("\\\\")


def display(raw: str) -> str:
    """Readable native form of a recorded path, or "" when it is not a path."""
    p = (raw or "").strip().strip('"')
    if not p:
        return ""
    if p.lower().startswith("file:"):
        u = urlparse(p)
        p = unquote(u.path)
        if u.netloc and u.netloc.lower() != "localhost":
            p = f"//{u.netloc}{p}"
        if re.match(r"^/[A-Za-z]:", p):  # /c:/Users -> c:/Users
            p = p[1:]
    if p.startswith("\\\\?\\UNC\\"):
        p = "\\\\" + p[8:]
    elif p.startswith("\\\\?\\") or p.startswith("//?/"):
        p = p[4:]
    if _is_windows_path(p) or (os.name == "nt" and "\\" in p):
        p = ntpath.normpath(p.replace("/", "\\"))
        if _WIN_DRIVE.match(p):
            p = p[0].upper() + p[1:]
        return p
    return posixpath.normpath(p)


def key(raw: str) -> str:
    """Comparison key: same folder -> same key. Windows paths compare case-insensitively."""
    p = display(raw)
    if _is_windows_path(p):
        return p.rstrip("\\").lower() if len(p) > 3 else p.lower()
    return p.rstrip("/") or "/"


def claude_project_dir(path: str) -> str:
    """Name Claude Code gives the session folder of `path` under ~/.claude/projects.

    Every character outside [A-Za-z0-9] becomes "-":
    C:\\Users\\me\\My Proj\\.claude  ->  C--Users-me-My-Proj--claude
    """
    return re.sub(r"[^A-Za-z0-9]", "-", display(path))


def is_within(child: str, parent: str) -> bool:
    c, p = key(child), key(parent)
    sep = "\\" if _is_windows_path(display(child)) else "/"
    return c == p or c.startswith(p.rstrip(sep) + sep)


TEMP_MARKERS = (
    "\\appdata\\local\\temp\\",
    "\\scratch-workspaces\\",
    "/tmp/",
    "/var/folders/",
)


def is_temporary(path: str) -> bool:
    k = key(path) + ("\\" if _is_windows_path(display(path)) else "/")
    return any(m in k for m in TEMP_MARKERS)


def is_cloud_synced(path: str) -> bool:
    """OneDrive, Dropbox, Google Drive, iCloud: a .git inside them is a known hazard."""
    k = key(path)
    return any(m in k for m in ("\\onedrive", "/onedrive", "dropbox", "google drive", "icloud", "mobile documents"))
