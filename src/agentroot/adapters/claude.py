"""Claude Code (CLI and IDE) and the Claude desktop app.

Claude Code home (~/.claude, or any CLAUDE_CONFIG_DIR such as ~/.claude-corp):
    projects/<encoded cwd>/<session-id>.jsonl   one file per session; every line carries "cwd"
    history.jsonl                                prompt history, field "project"
    ~/.claude.json (default home) or <home>/.claude.json   key "projects": { "<path>": {...} }

The folder name under projects/ is derived from the cwd (see paths.claude_project_dir), but
it is NOT always equal to it: the desktop app can file a session under one folder while its
cwd is another. The cwd inside the file is the truth.

Claude desktop home (%APPDATA%\\Claude, ~/.claude-enterprise, ~/Library/Application Support/Claude):
    claude-code-sessions/**/*.json   fields cwd, originCwd, worktreePath
    git-worktrees.json               worktrees.<name>.{path, baseRepo}
"""
from __future__ import annotations

import glob
import json
import os
from collections.abc import Iterator

from agentroot import paths
from agentroot.adapters.util import env_dir, load_json, looks_like_path, mtime_iso
from agentroot.model import Home, Reference, Session

CODE = "claude-code"
DESKTOP = "claude-desktop"
SHARED_PREFIX = "projects/ is shared with "
_MAX_LINES = 400


def homes(user_home: str) -> list[Home]:
    found: list[Home] = []
    seen: set[str] = set()

    def add(agent: str, path: str, note: str = "") -> None:
        k = paths.key(path)
        if k not in seen and os.path.isdir(path):
            seen.add(k)
            found.append(Home(agent, path, note))

    # Several config dirs can share one projects/ through a junction or symlink
    # (~/.claude-corp/projects -> ~/.claude/projects). Count those sessions once.
    real_projects: dict[str, str] = {}

    def add_code(path: str, note: str = "") -> None:
        proj = os.path.join(path, "projects")
        real = paths.key(os.path.realpath(proj)) if os.path.isdir(proj) else ""
        if real and real in real_projects:
            note = f"{SHARED_PREFIX}{real_projects[real]}"
        elif real:
            real_projects[real] = path
        add(CODE, path, note)

    env = env_dir(user_home, "CLAUDE_CONFIG_DIR")
    if env:
        add_code(env, "CLAUDE_CONFIG_DIR")
    add_code(os.path.join(user_home, ".claude"))
    for d in sorted(glob.glob(os.path.join(user_home, ".claude-*"))):
        if os.path.isdir(os.path.join(d, "projects")):
            add_code(d, "extra config dir")

    desktop_candidates = [
        os.path.join(env_dir(user_home, "APPDATA", "AppData", "Roaming"), "Claude"),
        os.path.join(user_home, "Library", "Application Support", "Claude"),
        os.path.join(user_home, ".config", "Claude"),
    ] + sorted(glob.glob(os.path.join(user_home, ".claude-*")))
    for d in desktop_candidates:
        if os.path.isdir(os.path.join(d, "claude-code-sessions")):
            add(DESKTOP, d)
    return found


def _first_cwd(jsonl: str) -> str:
    try:
        with open(jsonl, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= _MAX_LINES:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if cwd:
                    return cwd
    except OSError:
        pass
    return ""


def sessions(home: Home) -> Iterator[Session]:
    if home.agent == DESKTOP:
        yield from _desktop_sessions(home)
        return
    if home.note.startswith(SHARED_PREFIX):
        return  # same files as another home; counted there
    # projects/<dir>/<id>.jsonl are sessions; projects/<dir>/<id>/subagents/*.jsonl are their
    # subagent transcripts (they carry cwd too, but belong to the parent session).
    for jsonl in glob.glob(os.path.join(home.path, "projects", "*", "*.jsonl")):
        folder = os.path.basename(os.path.dirname(jsonl))
        cwd = _first_cwd(jsonl)
        warnings: tuple[str, ...] = ()
        if not cwd:
            warnings = ("no cwd recorded",)
        elif paths.claude_project_dir(cwd) != folder:
            warnings = (f"filed under {folder}",)
        yield Session(
            agent=CODE,
            home=home.path,
            id=os.path.splitext(os.path.basename(jsonl))[0],
            path=cwd,
            updated=mtime_iso(jsonl),
            store=os.path.relpath(jsonl, home.path),
            warnings=warnings,
        )


def _desktop_sessions(home: Home) -> Iterator[Session]:
    for f in glob.glob(os.path.join(home.path, "claude-code-sessions", "**", "*.json"), recursive=True):
        try:
            data = load_json(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        cwd = data.get("cwd") or data.get("worktreePath") or data.get("originCwd") or ""
        sid = data.get("sessionId") or data.get("id") or os.path.splitext(os.path.basename(f))[0]
        yield Session(
            agent=DESKTOP,
            home=home.path,
            id=str(sid),
            path=cwd,
            updated=mtime_iso(f),
            store=os.path.relpath(f, home.path),
        )


def references(home: Home) -> Iterator[Reference]:
    if home.agent == DESKTOP:
        wt = os.path.join(home.path, "git-worktrees.json")
        if os.path.isfile(wt):
            try:
                data = load_json(wt)
            except (OSError, ValueError):
                data = {}
            for name, item in (data.get("worktrees") or {}).items():
                for field in ("path", "baseRepo"):
                    if isinstance(item, dict) and item.get(field):
                        yield Reference(DESKTOP, home.path, item[field], f"git-worktrees.json#worktrees.{name}.{field}", "worktree")
        return

    # The default home (~/.claude) is configured by ~/.claude.json beside it; a CLAUDE_CONFIG_DIR
    # home keeps its own .claude.json inside. ~/.claude/.claude.json can exist too (seen on real
    # machines), so read every candidate and label which file each path came from.
    candidates = [os.path.join(home.path, ".claude.json")]
    if os.path.basename(home.path) == ".claude":
        candidates.insert(0, os.path.join(os.path.dirname(home.path), ".claude.json"))
    for cfg in candidates:
        if not os.path.isfile(cfg):
            continue
        try:
            data = load_json(cfg)
        except (OSError, ValueError):
            continue
        label = os.path.relpath(cfg, os.path.dirname(home.path)).replace("\\", "/")
        for p in (data.get("projects") or {}):
            if looks_like_path(p):
                yield Reference(CODE, home.path, p, f"{label}#projects", "project")

    hist = os.path.join(home.path, "history.jsonl")
    if os.path.isfile(hist):
        seen: set[str] = set()
        with open(hist, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    p = json.loads(line).get("project")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if p and paths.key(p) not in seen:
                    seen.add(paths.key(p))
                    yield Reference(CODE, home.path, p, "history.jsonl#project", "recent")
