"""Google Antigravity (app, IDE and the `agy` CLI) and the Gemini CLI, which share ~/.gemini.

Each Antigravity flavor has its own home under ~/.gemini:
    antigravity/, antigravity-cli/, antigravity-ide/   (antigravity-backup/ is a copy)
        conversation_summaries.db    conversation_summaries(conversation_id, workspace_uris JSON list
                                     of file:/// URIs, project_id, last_modified_time, ...)
        conversations/<id>.db        per-conversation SQLite, steps.step_payload = protobuf blobs
        conversations/<id>.pb        older format, raw protobuf. Either way: never rewrite in place,
                                     protobuf strings are length-prefixed.
        brain/<id>/.system_generated/logs/transcript*.jsonl   readable transcript, workspaceUris inside
        settings.json (cli)          trustedWorkspaces[]
    config/projects/<id>.json        Antigravity "projects": id, name, projectResources.resources[]
    projects.json                    Gemini CLI: { "projects": { "<lower-cased path>": "<slug>" } }
    history/<slug>/.project_root     Gemini CLI: the path the slug belongs to
    tmp/<slug>/.project_root         Gemini CLI: same, next to chats/ and logs.json
    trustedFolders.json              Gemini CLI trust list, keys are paths (c:/lower/forward)
    config/config.json               permission grants such as read_file(C:\\proj)
    %APPDATA%\\Antigravity\\User\\workspaceStorage\\*\\workspace.json   VS Code-style {"folder": "file:///c%3A/..."}
    %APPDATA%\\Antigravity\\User\\globalStorage\\storage.json, state.vscdb (ItemTable: sidebarWorkspaces, recents)

Moving a folder makes the Gemini CLI allocate a new slug (proj-1) and orphan history/<slug>.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections.abc import Iterator

from agentroot.adapters.util import env_dir, iso, load_json, looks_like_path, strings
from agentroot.model import Home, Reference, Session
from agentroot.snapshot import columns, has_table, open_copy

AGENT = "antigravity"


def homes(user_home: str) -> list[Home]:
    gem = os.path.join(user_home, ".gemini")
    found = []
    for d in sorted(glob.glob(os.path.join(gem, "antigravity*"))):
        if os.path.isfile(os.path.join(d, "conversation_summaries.db")) or os.path.isdir(os.path.join(d, "conversations")):
            note = "backup copy" if d.endswith("-backup") else ""
            found.append(Home(AGENT, d, note))
    if os.path.isdir(gem):
        found.append(Home(AGENT, gem, "shared ~/.gemini registries"))
    return found


def sessions(home: Home) -> Iterator[Session]:
    db = os.path.join(home.path, "conversation_summaries.db")
    if not os.path.isfile(db):
        return
    with open_copy(db) as con:
        if not has_table(con, "conversation_summaries"):
            return
        cols = columns(con, "conversation_summaries")
        want = [c for c in ("conversation_id", "workspace_uris", "project_id", "last_modified_time") if c in cols]
        for row in con.execute(f"select {', '.join(want)} from conversation_summaries"):
            r = dict(zip(want, row))
            uris = _uris(r.get("workspace_uris"))
            warnings = ("backup copy",) if home.note == "backup copy" else ()
            if len(uris) > 1:
                warnings += (f"{len(uris)} workspaces",)
            yield Session(
                agent=AGENT,
                home=home.path,
                id=str(r.get("conversation_id")),
                path=uris[0] if uris else "",
                updated=iso(r.get("last_modified_time")),
                store="conversation_summaries.db#conversation_summaries",
                warnings=warnings,
            )


def _uris(value) -> list[str]:
    if not value:
        return []
    try:
        v = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return [str(value)]
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def references(home: Home) -> Iterator[Reference]:
    if home.note != "shared ~/.gemini registries":
        return
    gem = home.path
    for f in glob.glob(os.path.join(gem, "config", "projects", "*.json")):
        try:
            data = load_json(f)
        except (OSError, ValueError):
            continue
        for field, value in strings(data.get("projectResources") or {}):
            if looks_like_path(value):
                yield Reference(AGENT, gem, value, f"config/projects/{os.path.basename(f)}#projectResources.{field}", "project")
    pj = os.path.join(gem, "projects.json")
    if os.path.isfile(pj):
        try:
            for p in (load_json(pj).get("projects") or {}):
                yield Reference(AGENT, gem, p, "projects.json#projects", "project")
        except (OSError, ValueError, AttributeError):
            pass
    for f in glob.glob(os.path.join(gem, "history", "*", ".project_root")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                p = fh.read().strip()
        except OSError:
            continue
        if p:
            yield Reference(AGENT, gem, p, f"history/{os.path.basename(os.path.dirname(f))}/.project_root", "project")
    tf = os.path.join(gem, "trustedFolders.json")
    if os.path.isfile(tf):
        try:
            for p in load_json(tf):
                yield Reference(AGENT, gem, p, "trustedFolders.json", "trust")
        except (OSError, ValueError, TypeError):
            pass
    for f in glob.glob(os.path.join(gem, "tmp", "*", ".project_root")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                p = fh.read().strip()
        except OSError:
            continue
        if p:
            yield Reference(AGENT, gem, p, f"tmp/{os.path.basename(os.path.dirname(f))}/.project_root", "project")
    # Path-bearing JSON configs: trust lists and permission grants such as read_file(C:\proj).
    for rel, role in (("antigravity-cli/settings.json", "trust"), ("config/config.json", "trust")):
        yield from _json_refs(gem, os.path.join(gem, *rel.split("/")), rel, role)

    appdata = env_dir(os.path.dirname(gem), "APPDATA", "AppData", "Roaming")
    user = os.path.join(appdata, "Antigravity", "User")
    for f in glob.glob(os.path.join(user, "workspaceStorage", "*", "workspace.json")):
        try:
            folder = load_json(f).get("folder")
        except (OSError, ValueError, AttributeError):
            continue
        if folder:
            yield Reference(AGENT, gem, folder, "Antigravity/User/workspaceStorage/*/workspace.json#folder", "recent")
    yield from _json_refs(gem, os.path.join(user, "globalStorage", "storage.json"),
                          "Antigravity/User/globalStorage/storage.json", "recent")
    vscdb = os.path.join(user, "globalStorage", "state.vscdb")
    if os.path.isfile(vscdb):
        with open_copy(vscdb) as con:
            if has_table(con, "ItemTable"):
                for k, v in con.execute("select key, value from ItemTable"):
                    for p in _paths_in_text(v):
                        yield Reference(AGENT, gem, p, f"Antigravity/User/globalStorage/state.vscdb#ItemTable.{k}", "recent")


_GRANT = re.compile(r"\(([A-Za-z]:[\\/][^()]*)\)")


def _paths_in_text(value) -> list[str]:
    """Paths inside a JSON value or a grant string like read_file(C:\\proj)."""
    if value is None:
        return []
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        data = value
    out = []
    items = strings(data) if not isinstance(data, str) else [("", data)]
    for field, s in items:
        if looks_like_path(s):
            out.append(s)
        else:
            out += _GRANT.findall(s)
        if field and looks_like_path(field.split(".")[-1]):  # paths used as keys
            out.append(field.split(".")[-1])
    return out


def _json_refs(home: str, path: str, store: str, role: str) -> Iterator[Reference]:
    if not os.path.isfile(path):
        return
    try:
        data = load_json(path)
    except (OSError, ValueError):
        return
    seen = set()
    for _, value in strings(data):
        for p in (_paths_in_text(value) if not looks_like_path(value) else [value]):
            if p not in seen:
                seen.add(p)
                yield Reference(AGENT, home, p, store, role)
    if isinstance(data, dict):  # some stores key by path
        for k in _keys(data):
            if looks_like_path(k) and k not in seen:
                seen.add(k)
                yield Reference(AGENT, home, k, store, role)


def _keys(obj) -> Iterator[str]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                yield str(k)
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
