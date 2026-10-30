"""Turn every session and reference of every agent into one catalog of projects.

A project is identified by its git remote (credentials stripped). Folders without a remote
are their own project, keyed by the main clone's path. Sessions recorded in a subfolder roll
up to the working tree that contains it, so "repo" and "repo/frontend" are one location.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from agentroot import gitinfo, paths
from agentroot.adapters import ALL
from agentroot.model import Home, Location, Project, Reference, Session

NO_PROJECT = "(outside any project)"


@dataclass
class Scan:
    user_home: str
    homes: list[Home] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def collect(user_home: str) -> Scan:
    scan = Scan(user_home)
    for adapter in ALL:
        for home in adapter.homes(user_home):
            scan.homes.append(home)
            for kind, fn in (("sessions", adapter.sessions), ("references", adapter.references)):
                try:
                    getattr(scan, kind).extend(fn(home))
                except Exception as e:  # one broken store must not hide the others
                    scan.errors.append(f"{home.agent} {home.path} {kind}: {type(e).__name__}: {e}")
    return scan


def _nearest_existing(path: str) -> str:
    cur = path
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            return ""
        cur = parent
    return cur


def _not_a_project(path: str, user_home: str) -> bool:
    k = paths.key(path)
    windir = paths.key(os.environ.get("WINDIR", "C:\\Windows"))
    return (
        k in (paths.key(user_home), paths.key(os.path.dirname(user_home)))
        or len(k.rstrip("\\/")) <= 2              # a drive root
        or paths.is_within(path, windir)
    )


def build(user_home: str) -> Scan:
    scan = collect(user_home)
    git_cache: dict[str, gitinfo.GitInfo | None] = {}
    projects: dict[str, Project] = {}
    locations: dict[tuple[str, str], Location] = {}

    def place(raw: str, remote_hint: str = "", create: bool = True) -> Location | None:
        disp = paths.display(raw)
        if not disp or os.path.isfile(disp):  # a file path is not a project location
            return None
        exists = os.path.exists(disp)
        probe = disp if exists else _nearest_existing(disp)
        if probe and probe not in git_cache:
            git_cache[probe] = gitinfo.find(probe, stop_at=user_home)
        gi = git_cache.get(probe) if probe else None
        if gi and not exists and paths.key(gi.root) in (paths.key(user_home),):
            gi = None

        if _not_a_project(disp, user_home):
            pkey, name, remote, loc_path, kind = NO_PROJECT, NO_PROJECT, "", disp, "folder"
        elif gi:
            remote = gi.remote
            pkey = gi.remote_key or paths.key(gi.main_root or gi.root)
            name = (gi.remote_key.rsplit("/", 1)[-1] if gi.remote_key else os.path.basename(gi.main_root or gi.root))
            loc_path = gi.root if exists else disp
            kind = gi.kind if exists else "missing"
        else:
            hint = gitinfo.remote_key(remote_hint)
            remote = gitinfo.strip_credentials(remote_hint)
            pkey = hint or paths.key(disp)
            name = hint.rsplit("/", 1)[-1] if hint else os.path.basename(disp.rstrip("\\/")) or disp
            loc_path = disp
            kind = "folder" if exists else "missing"

        proj = projects.get(pkey)
        lk = (pkey, paths.key(loc_path))
        if not create and lk not in locations and (proj is None or not exists):
            return None
        if proj is None:
            proj = projects[pkey] = Project(key=pkey, name=name, remote=remote)
        loc = locations.get(lk)
        if loc is None:
            loc = locations[lk] = Location(
                path=loc_path,
                exists=exists,
                kind=kind,
                temporary=paths.is_temporary(loc_path),
                cloud_synced=paths.is_cloud_synced(loc_path),
            )
            proj.locations.append(loc)
        return loc

    for s in scan.sessions:
        loc = place(s.path, s.remote_hint)
        if loc is None:
            continue
        loc.sessions[s.agent] = loc.sessions.get(s.agent, 0) + 1
        loc.last_activity = max(loc.last_activity, s.updated)
    # References only add folders: a trust entry or a "recent" pointing at a folder that no
    # session uses and that no longer exists is noise, not a project.
    for r in scan.references:
        loc = place(r.path, create=r.role in ("project", "worktree"))
        if loc is not None:
            loc.references[r.agent] = loc.references.get(r.agent, 0) + 1

    scan.projects = sorted(projects.values(), key=lambda p: (p.key != NO_PROJECT, p.last_activity), reverse=True)
    return scan


def flags(project: Project) -> list[str]:
    out = []
    clones = [l for l in project.locations if l.kind == "clone"]
    if len(clones) > 1:
        out.append(f"{len(clones)} clones")
    worktrees = [l for l in project.locations if l.kind == "worktree"]
    if worktrees:
        out.append(f"{len(worktrees)} worktrees")
    missing = [l for l in project.locations if l.kind == "missing" and sum(l.sessions.values())]
    if missing:
        out.append(f"{sum(sum(l.sessions.values()) for l in missing)} sessions point to missing folders")
    if any(l.cloud_synced and l.kind in ("clone", "worktree") for l in project.locations):
        out.append("git inside a cloud-synced folder")
    if any(l.temporary for l in project.locations):
        out.append("temporary folders")
    return out
