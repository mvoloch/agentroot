"""OpenAI Codex (CLI, IDE extension and desktop app). Home: $CODEX_HOME or ~/.codex.

    sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]   conversations; most are zstd-compressed.
                                                first record: {"type":"session_meta","payload":{"id","cwd","git":{...}}}
    archived_sessions/rollout-*.jsonl.zst
    state_<N>.sqlite                            the app's thread list: threads(id, cwd "\\\\?\\C:\\...", rollout_path,
                                                git_origin_url, project_id, ...), projects, project_roots(path)
    sqlite/state_<N>.sqlite                     a DIFFERENT, smaller store with the same file name
    sqlite/codex-dev.db                         desktop catalog: local_thread_catalog.cwd, automations.cwds
    .codex-global-state.json                    desktop UI state: local-projects.<id>.rootPaths[] and more
    config.toml                                 [projects.'<lower-cased path>'] trust_level
    thread_history_1.sqlite                     turn projections with BYTE OFFSETS into the rollout files:
                                                never rewrite rollout content, or these offsets go stale.
    worktrees/<4 hex>/<repo>/                   app-created worktrees; the Microsoft Store build also
                                                keeps some under Packages/OpenAI.Codex_*/LocalCache/Local/.codex/worktrees
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import tomllib
from collections.abc import Iterator

from agentroot import gitinfo
from agentroot.adapters.util import iso, load_json, looks_like_path, mtime_iso, strings
from agentroot.model import Home, Reference, Session
from agentroot.snapshot import columns, has_table, open_copy

try:  # Python 3.14+
    from compression import zstd as _zstd
except ImportError:  # pragma: no cover - depends on the interpreter
    _zstd = None

AGENT = "codex"
_ROOT_FIELD = re.compile(r"(rootPaths|workspace-roots|[wW]orkspaceRoots|writable-roots|writableRoots|root-hints|\.cwd)(\.<id>)?(\[\])?$")


def homes(user_home: str) -> list[Home]:
    path = os.environ.get("CODEX_HOME") or os.path.join(user_home, ".codex")
    return [Home(AGENT, path)] if os.path.isdir(path) else []


def _state_dbs(home: Home) -> list[str]:
    """Highest-numbered state_<N>.sqlite in the home, then the one under sqlite/ (a separate store)."""
    out = []
    for folder in (home.path, os.path.join(home.path, "sqlite")):
        best, best_n = "", -1
        for f in glob.glob(os.path.join(folder, "state_*.sqlite")):
            m = re.search(r"state_(\d+)\.sqlite$", f)
            if m and int(m.group(1)) > best_n:
                best, best_n = f, int(m.group(1))
        if best:
            out.append(best)
    return out


def sessions(home: Home) -> Iterator[Session]:
    indexed: set[str] = set()
    for db in _state_dbs(home):
        store = os.path.relpath(db, home.path)
        with open_copy(db) as con:
            if not has_table(con, "threads"):
                continue
            cols = columns(con, "threads")
            want = [c for c in ("id", "cwd", "updated_at", "git_origin_url", "archived") if c in cols]
            for row in con.execute(f"select {', '.join(want)} from threads"):
                r = dict(zip(want, row))
                sid = str(r.get("id"))
                if sid in indexed:
                    continue
                indexed.add(sid)
                yield Session(
                    agent=AGENT,
                    home=home.path,
                    id=sid,
                    path=r.get("cwd") or "",
                    updated=iso(r.get("updated_at")),
                    remote_hint=gitinfo.strip_credentials(r.get("git_origin_url") or ""),
                    store=f"{store}#threads",
                    warnings=("archived",) if r.get("archived") else (),
                )
    # Rollouts the indexes do not know about are still conversations on disk.
    for f in _rollouts(home):
        meta = session_meta(f)
        sid = str(meta.get("id") or "")
        if not sid or sid in indexed:
            continue
        indexed.add(sid)
        yield Session(
            agent=AGENT,
            home=home.path,
            id=sid,
            path=meta.get("cwd") or "",
            updated=mtime_iso(f),
            remote_hint=gitinfo.strip_credentials(((meta.get("git") or {}).get("repository_url")) or ""),
            store=os.path.relpath(f, home.path),
            warnings=("not in the app's index",),
        )


def _rollouts(home: Home) -> list[str]:
    out = []
    for sub in ("sessions", "archived_sessions"):
        for pat in ("rollout-*.jsonl", "rollout-*.jsonl.zst"):
            out += glob.glob(os.path.join(home.path, sub, "**", pat), recursive=True)
    return out


def session_meta(rollout: str) -> dict:
    """payload of the first record; reads .zst too when the interpreter supports it."""
    try:
        if rollout.endswith(".zst"):
            if _zstd is None:
                return {}
            with _zstd.open(rollout, "rb") as raw:
                first = io.TextIOWrapper(raw, encoding="utf-8", errors="replace").readline()
        else:
            with open(rollout, encoding="utf-8", errors="replace") as f:
                first = f.readline()
        rec = json.loads(first or "{}")
    except (OSError, ValueError, EOFError):
        return {}
    payload = rec.get("payload") if isinstance(rec, dict) else None
    return payload if isinstance(payload, dict) else {}


def references(home: Home) -> Iterator[Reference]:
    for db in _state_dbs(home):
        store = os.path.relpath(db, home.path)
        with open_copy(db) as con:
            if has_table(con, "project_roots"):
                for (p,) in con.execute("select path from project_roots"):
                    if p:
                        yield Reference(AGENT, home.path, p, f"{store}#project_roots", "project")

    dev = os.path.join(home.path, "sqlite", "codex-dev.db")
    if os.path.isfile(dev):
        with open_copy(dev) as con:
            if has_table(con, "local_thread_catalog") and "cwd" in columns(con, "local_thread_catalog"):
                for (p,) in con.execute("select distinct cwd from local_thread_catalog where cwd is not null"):
                    yield Reference(AGENT, home.path, p, "sqlite/codex-dev.db#local_thread_catalog.cwd", "recent")
            if has_table(con, "automations") and "cwds" in columns(con, "automations"):
                for (v,) in con.execute("select cwds from automations where cwds is not null"):
                    for p in _json_paths(v):
                        yield Reference(AGENT, home.path, p, "sqlite/codex-dev.db#automations.cwds", "project")

    gs = os.path.join(home.path, ".codex-global-state.json")
    if os.path.isfile(gs):
        try:
            data = load_json(gs)
        except (OSError, ValueError):
            data = {}
        # Only fields that hold folders (roots, cwds). The file also caches artifact file paths,
        # MCP resource URIs and prompt text, which are not project locations.
        seen: set[tuple[str, str]] = set()
        for field, value in strings(data):
            f = re.sub(r"\.?[0-9a-f-]{8,}|local-[0-9a-f]{32}", ".<id>", field)
            if not _ROOT_FIELD.search(f) or not looks_like_path(value) or (f, value) in seen:
                continue
            seen.add((f, value))
            role = "project" if "rootPaths" in f or "workspace-roots" in f else "recent"
            yield Reference(AGENT, home.path, value, f".codex-global-state.json#{f}", role)

    cfg = os.path.join(home.path, "config.toml")
    if os.path.isfile(cfg):
        try:
            with open(cfg, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        for p in (data.get("projects") or {}):
            yield Reference(AGENT, home.path, p, "config.toml#projects", "trust")

    local = os.environ.get("LOCALAPPDATA", os.path.join(os.path.dirname(home.path), "AppData", "Local"))
    roots = [os.path.join(home.path, "worktrees")] + glob.glob(
        os.path.join(local, "Packages", "OpenAI.Codex_*", "LocalCache", "Local", ".codex", "worktrees"))
    for root in roots:
        for wt in glob.glob(os.path.join(root, "*", "*")):
            if os.path.isdir(wt):
                yield Reference(AGENT, home.path, wt, "worktrees/", "worktree")


def _json_paths(value) -> list[str]:
    try:
        v = json.loads(value)
    except (TypeError, ValueError):
        return [str(value)] if looks_like_path(str(value)) else []
    return [s for _, s in strings(v) if looks_like_path(s)]
