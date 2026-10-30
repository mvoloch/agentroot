"""Read git metadata straight from disk, without running git.

Never returns credentials: remote URLs are stripped of any user:password@ part, because
real setups embed tokens there (https://user:TOKEN@host/repo.git).
"""
from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class GitInfo:
    root: str            # working-tree root that contains this path
    kind: str            # "clone" | "worktree"
    common_dir: str      # the shared .git directory
    main_root: str       # working tree of the main clone ("" for bare repos)
    remote: str          # origin URL without credentials ("" when there is none)
    remote_key: str      # host/owner/repo, lower-cased: same repo -> same key


def strip_credentials(url: str) -> str:
    url = (url or "").strip()
    if "://" in url:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    return url  # scp-style git@host:owner/repo has no secret in it


def remote_key(url: str) -> str:
    url = strip_credentials(url)
    if not url:
        return ""
    if "://" in url:
        parts = urlsplit(url)
        host, path = (parts.hostname or "").lower(), parts.path
    else:
        m = re.match(r"^(?:[^@]+@)?([^:]+):(.*)$", url)
        if not m:  # a local path used as remote
            return url.replace("\\", "/").rstrip("/").lower()
        host, path = m.group(1).lower(), m.group(2)
    path = re.sub(r"\.git$", "", path.strip("/")).lower()
    return f"{host}/{path}"


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().strip()


def _origin(common_dir: str) -> str:
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(os.path.join(common_dir, "config"), encoding="utf-8")
    except configparser.Error:
        return ""
    sections = [s for s in cfg.sections() if s.startswith("remote ")]
    preferred = [s for s in sections if s == 'remote "origin"'] or sections
    return strip_credentials(cfg.get(preferred[0], "url", fallback="")) if preferred else ""


def find(path: str, stop_at: str | None = None) -> GitInfo | None:
    """GitInfo of the repository that contains `path`, walking up; None when not in one."""
    cur = os.path.abspath(path)
    while True:
        dotgit = os.path.join(cur, ".git")
        if os.path.isdir(dotgit):
            remote = _origin(dotgit)
            return GitInfo(cur, "clone", dotgit, cur, remote, remote_key(remote))
        if os.path.isfile(dotgit):
            info = _from_gitfile(cur, dotgit)
            if info:
                return info
        parent = os.path.dirname(cur)
        if parent == cur or (stop_at and os.path.normcase(cur) == os.path.normcase(stop_at)):
            return None
        cur = parent


def _from_gitfile(root: str, dotgit: str) -> GitInfo | None:
    m = re.match(r"gitdir:\s*(.+)", _read(dotgit))
    if not m:
        return None
    gitdir = m.group(1).strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(root, gitdir))
    common = gitdir
    commondir_file = os.path.join(gitdir, "commondir")
    if os.path.isfile(commondir_file):
        c = _read(commondir_file)
        common = os.path.normpath(c if os.path.isabs(c) else os.path.join(gitdir, c))
    kind = "worktree" if os.path.normcase(common) != os.path.normcase(gitdir) else "clone"
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else ""
    remote = _origin(common)
    return GitInfo(root, kind, common, main, remote, remote_key(remote))
