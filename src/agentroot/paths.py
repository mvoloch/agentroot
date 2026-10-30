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
from urllib.parse import quote, unquote, urlparse

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
    if not c or not p:
        return False
    sep = "\\" if _is_windows_path(display(child)) else "/"
    return c == p or c.startswith(p.rstrip(sep) + sep)


def remap(raw: str, src: str, dst: str) -> str | None:
    """`raw` with the `src` folder replaced by `dst`, written in the SAME spelling as `raw`.

    None when `raw` is not `src` or inside it. Each agent reads its own spelling back, so a
    Codex `\\\\?\\C:\\...` stays extended, a Gemini `c:/users/...` stays lower-case with forward
    slashes, an Antigravity `file:///c%3A/...` stays a percent-encoded URI.
    """
    if not raw or not is_within(raw, src):
        return None
    old_disp, src_disp, dst_disp = display(raw), display(src), display(dst)
    win = _is_windows_path(old_disp)
    sep = "\\" if win else "/"
    suffix = old_disp[len(src_disp.rstrip("\\/")):]
    new_disp = dst_disp.rstrip("\\/") + suffix
    stripped = raw.strip()
    trailing = len(stripped) > 3 and stripped[-1] in "\\/"

    if stripped.lower().startswith("file:"):
        out = _as_uri(new_disp, stripped, win)
    else:
        body = stripped[4:] if stripped.startswith(("\\\\?\\", "//?/")) else stripped
        out = new_disp
        if win and "/" in body and "\\" not in body:
            out = out.replace("\\", "/")
        if win and body == body.lower() and body != body.upper():
            out = out.lower()
        if stripped.startswith("\\\\?\\"):
            out = "\\\\?\\" + out
    if trailing and not out.endswith(("/", "\\")):
        out += "/" if stripped.endswith("/") else sep
    return out


def _as_uri(new_disp: str, raw: str, win: bool) -> str:
    m = re.match(r"(?i)file:///([a-z])(%3a|:)(.*)$", raw)
    rest_raw = m.group(3) if m else raw[7:]
    encode = " " not in rest_raw  # a literal space means this store does not percent-encode
    if win and _WIN_DRIVE.match(new_disp):
        drive = new_disp[0].lower() if (m and m.group(1).islower()) else new_disp[0].upper()
        colon = m.group(2) if m else ":"
        rest = new_disp[2:].replace("\\", "/")
        return f"file:///{drive}{colon}{quote(rest, safe='/') if encode else rest}"
    p = new_disp.replace("\\", "/")
    return "file://" + (quote(p, safe="/") if encode else p)


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
