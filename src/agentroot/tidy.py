"""Propose how to tidy every copy of every project on disk. Read-only: nothing is moved here.

Agents leave copies everywhere: clones in odd folders, worktrees per task, copies inside
conversation folders. `propose()` finds every git working tree on disk, checks what in each
one exists nowhere else, and proposes one action per folder:

    MAIN       the project's main copy: moves to <root>/<name> (or is already there)
    WITH_MAIN  inside the main copy and in use or holding work: moves with it
    GATHER     another copy in use or holding work found nowhere else: moves into the project,
               <root>/<name>/.worktrees/<folder>, so each project is one folder
    ARCHIVE    idle for 30 days and holding nothing that is not elsewhere: moves to
               <root>/_arquivo/<date>/; you delete the archive yourself later
    DECIDE     sits in a cloud-synced folder (moving it out stops syncing it), could not be
               checked, or holds work but its project has no main copy to gather it into
    ACTIVE     in use, but its project has no main copy outside an agent's folders: stays
    AGENT      inside an agent's own folder (Codex worktrees, app data): the agent manages it
    KEEP       a folder agents worked in that is not a git repository: nothing to compare against
    SCRATCH    a temporary or scratch folder

Applying a reviewed proposal uses `move`, so every step is journaled and undoable.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field

from agentroot import catalog, gitinfo, paths

IDLE_DAYS = 30
WORKTREES = ".worktrees"  # where a project's other copies are gathered, git-ignored through .git/info/exclude
SKIP = {"node_modules", ".venv", "venv", "__pycache__", ".next", "AppData", "Library", ".cache", ".npm", ".nuget",
        ".gradle", ".rustup", ".cargo", "go", ".m2", ".pyenv", "scoop", "site-packages"}
REBUILDABLE = {"node_modules", ".venv", "venv", "__pycache__", ".next", ".turbo", ".pytest_cache", ".mypy_cache",
               ".ruff_cache", ".parcel-cache"}
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Tree:
    path: str
    kind: str                    # clone | worktree | folder
    group: str = ""              # first commit, else remote, else path: copies of one repo share it
    name: str = ""
    remote: str = ""
    main_root: str = ""          # for a worktree, the clone whose .git holds its commits
    branch: str = ""
    changed: int = 0             # tracked files with uncommitted changes
    untracked: list[str] = field(default_factory=list)
    untracked_count: int = 0
    unique: int | None = 0       # commits found in no remote and not in the main copy (None: unknown)
    stash: int = 0
    last_commit: str = ""
    last_file: str = ""
    sessions: int = 0
    last_session: str = ""
    shallow: bool = False        # cloned with --depth: its first commit is a cut, not the real start
    mb: float = 0.0
    regen_mb: float = 0.0        # node_modules, .venv, caches: rebuilt by npm/pip
    action: str = ""
    reason: str = ""
    dst: str = ""

    @property
    def last_activity(self) -> str:
        return max(self.last_file, self.last_commit, self.last_session)


def _git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", cwd, *args], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# ----------------------------------------------------------------------------- discovery


def roots(user_home: str, scan: catalog.Scan) -> list[str]:
    """The home, Codex's worktree folder, and every top-level folder outside the home where an agent worked."""
    out = [user_home, os.path.join(user_home, ".codex", "worktrees")]
    for p in scan.projects:
        for loc in p.locations:
            if loc.exists and not paths.is_within(loc.path, user_home):
                drive, rest = os.path.splitdrive(loc.path)
                top = rest.strip("\\/").split(os.sep)[0] if rest.strip("\\/") else ""
                if top:
                    out.append(os.path.join(drive + os.sep, top))
    seen, unique = set(), []
    for r in out:
        if os.path.isdir(r) and paths.key(r) not in seen:
            seen.add(paths.key(r))
            unique.append(r)
    return unique


def discover(user_home: str, search: list[str]) -> list[str]:
    """Every git working tree under `search`. Dot-folders of the home (agent data) are not entered."""
    found: dict[str, str] = {}
    home = paths.key(user_home)
    for root in search:
        for dp, dns, fns in os.walk(root, onerror=lambda e: None):
            if ".git" in dns or ".git" in fns:
                found.setdefault(paths.key(dp), dp)
            dns[:] = [d for d in dns if d != ".git" and d not in SKIP
                      and not (paths.key(dp) == home and d.startswith("."))]
    return sorted(found.values(), key=paths.key)


def _measure(t: Tree, inner: set[str]) -> None:
    """Size, rebuildable size and newest file, not counting nested working trees (measured on their own)."""
    total = regen = newest = 0
    for dp, dns, fns in os.walk(t.path, onerror=lambda e: None):
        for d in [d for d in dns if d in REBUILDABLE]:
            for dp2, _, f2 in os.walk(os.path.join(dp, d), onerror=lambda e: None):
                for f in f2:
                    try:
                        regen += os.lstat(os.path.join(dp2, f)).st_size
                    except OSError:
                        pass
        dns[:] = [d for d in dns if d not in REBUILDABLE and paths.key(os.path.join(dp, d)) not in inner]
        in_git = ".git" in dp.split(os.sep)
        for f in fns:
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            total += st.st_size
            if not in_git:
                newest = max(newest, st.st_mtime)
    t.mb, t.regen_mb = round(total / 2**20, 1), round(regen / 2**20, 1)
    t.last_file = dt.date.fromtimestamp(newest).isoformat() if newest else ""


def _facts(path: str) -> Tree:
    gi = gitinfo.find(path)
    t = Tree(path, gi.kind if gi else "clone", remote=gi.remote if gi else "", main_root=gi.main_root if gi else "")
    status = _git(path, "status", "--porcelain")
    if status is None:
        t.unique = None
        t.reason = "git could not read it"
        return t
    lines = [x for x in status.splitlines() if x.strip()]
    t.changed = sum(not x.startswith("??") for x in lines)
    untracked = [x[3:] for x in lines if x.startswith("??")]
    t.untracked, t.untracked_count = untracked[:5], len(untracked)
    t.branch = (_git(path, "branch", "--show-current") or "").strip()
    t.last_commit = (_git(path, "log", "-1", "--format=%cs") or "").strip()
    first = sorted((_git(path, "rev-list", "--max-parents=0", "HEAD") or "").split())
    # in a shallow clone (--depth) the "first" commit is only where the history was cut
    t.shallow = (_git(path, "rev-parse", "--is-shallow-repository") or "").strip() == "true"
    # Same first commit = same history, whatever the remote says (copies cloned from a local path or a bundle).
    t.group = ("root:" + first[0] if first else "") or (gi.remote_key if gi and gi.remote_key else "") or "path:" + paths.key(path)
    t.name = (gi.remote_key.rsplit("/", 1)[-1] if gi and gi.remote_key
              else os.path.basename(t.main_root or path))
    if t.kind == "clone":
        t.stash = len((_git(path, "stash", "list") or "").splitlines())
    return t


def survey(user_home: str, search: list[str] | None = None, progress=None) -> list[Tree]:
    scan = catalog.build(user_home)
    trees = [_facts(p) for p in discover(user_home, search or roots(user_home, scan))]
    keys = {paths.key(t.path) for t in trees}
    for t in trees:
        _measure(t, {k for k in keys if k != paths.key(t.path) and paths.is_within(k, t.path)})
        if progress:
            progress(t)
    # Sessions belong to the innermost working tree that contains their folder; a folder outside
    # any repository becomes an entry of its own (outermost first, so subfolders roll up into it).
    by_key = {paths.key(t.path): t for t in trees}
    locs = [(p, loc) for p in scan.projects for loc in p.locations if loc.exists and sum(loc.sessions.values())]
    for p, loc in sorted(locs, key=lambda pl: len(paths.key(pl[1].path))):
        owners = [k for k in by_key if paths.is_within(loc.path, k)]
        if owners:
            t = by_key[max(owners, key=len)]
        elif p.key != catalog.NO_PROJECT:
            t = Tree(loc.path, "folder", group="path:" + paths.key(loc.path), name=os.path.basename(loc.path))
            _measure(t, {k for k in keys if paths.is_within(k, loc.path)})
            trees.append(t)
            by_key[paths.key(loc.path)] = t
        else:
            continue
        t.sessions += sum(loc.sessions.values())
        t.last_session = max(t.last_session, loc.last_activity[:10])
    return trees


# ----------------------------------------------------------------------------- proposal


def _agent_owned(path: str, user_home: str) -> bool:
    parts = paths.key(path).replace("/", "\\").split("\\")
    # a project's .claude/ holds worktrees (the user's work) but also plugins the agent installed
    in_dot_claude = any(p == ".claude" and (i + 1 == len(parts) or parts[i + 1] != "worktrees") for i, p in enumerate(parts))
    return in_dot_claude or any(paths.is_within(path, os.path.join(user_home, d))
                                for d in (".codex", ".claude", ".claude-enterprise", ".gemini", ".antigravity", "AppData", "Library"))


def _temporary(path: str, user_home: str) -> bool:
    """Temporary by where it sits below the home (the home itself may live anywhere)."""
    if paths.is_within(path, user_home):
        rel = os.sep + os.path.relpath(path, user_home).lower() + os.sep
        return any(m in rel.replace("/", os.sep) for m in paths.TEMP_MARKERS)
    return paths.is_temporary(path)


def _conversation_folder(path: str, user_home: str) -> bool:
    """Codex desktop opens each chat in Documents/Codex/<date>/<slug>: a workspace, not a project home."""
    base = os.path.join(user_home, "Documents", "Codex")
    return paths.is_within(path, base) and any(_DATED.match(p) for p in os.path.relpath(path, base).split(os.sep))


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-").lower() or "project"


def _unique_vs(copy: Tree, main: Tree | None) -> int | None:
    """Commits in a copy's branches that are in no remote and not in the main copy."""
    tips = (_git(copy.path, "for-each-ref", "--format=%(objectname)", "refs/heads") or "").split()
    total = 0
    for tip in tips:
        if main and _git(main.path, "cat-file", "-e", tip + "^{commit}") is not None:
            continue  # the main copy has this commit, hence its whole history
        n = _git(copy.path, "rev-list", "--count", tip, "--not", "--remotes")
        if n is None:
            return None
        total += int(n.strip() or 0)
    return total


def _unmerged(wt: Tree) -> int | None:
    """Commits on a worktree's branch that are in no remote and not in the default branch."""
    default = next((b for b in ("main", "master") if _git(wt.path, "rev-parse", "--verify", "-q", b) is not None), None)
    extra = [default] if default and default != wt.branch else []
    n = _git(wt.path, "rev-list", "--count", "HEAD", "--not", "--remotes", *extra)
    return int(n.strip()) if n and n.strip().isdigit() else None


def propose(trees: list[Tree], user_home: str, root: str, today: dt.date | None = None) -> list[Tree]:
    today = today or dt.date.today()
    idle_before = (today - dt.timedelta(days=IDLE_DAYS)).isoformat()
    archive = os.path.join(root, "_arquivo", today.isoformat())
    keys = [paths.key(t.path) for t in trees if t.kind != "folder"]  # only a repository nests a copy
    nested = {paths.key(t.path) for t in trees
              if any(k != paths.key(t.path) and paths.is_within(t.path, k) for k in keys)}
    taken = {paths.key(os.path.join(root, n)) for n in (os.listdir(root) if os.path.isdir(root) else [])}

    def free(path: str, tree: Tree) -> str:
        cand, n = path, 1
        while paths.key(cand) in taken and not paths.key(cand) == paths.key(tree.path):
            n += 1
            cand = f"{path}-{n}"
        taken.add(paths.key(cand))
        return cand

    groups: dict[str, list[Tree]] = {}
    for t in trees:
        groups.setdefault(t.group or "path:" + paths.key(t.path), []).append(t)
    # A shallow copy joins the project whose full clone has the commit its history was cut at.
    full = {g: [t for t in ts if t.kind == "clone" and not t.shallow] for g, ts in groups.items()}
    for t in [t for t in trees if t.shallow and t.group.startswith("root:")]:
        cut = t.group[5:]
        home_group = next((g for g, clones in full.items() if g != t.group and any(
            _git(c.path, "cat-file", "-e", cut + "^{commit}") is not None for c in clones)), None)
        if home_group:
            groups[t.group].remove(t)
            if not groups[t.group]:
                del groups[t.group]
            t.group, t.name = home_group, full[home_group][0].name
            groups[home_group].append(t)

    for group in groups.values():
        eligible = [t for t in group if t.kind == "clone" and paths.key(t.path) not in nested
                    and not _agent_owned(t.path, user_home) and not _conversation_folder(t.path, user_home)
                    and not _temporary(t.path, user_home) and "backup" not in paths.key(t.path)]
        main = max(eligible, key=lambda t: (paths.is_within(t.path, root), t.sessions, t.last_activity), default=None)
        for t in sorted(group, key=lambda t: t is not main):  # the main first: copies gather into its destination
            _classify(t, main, user_home, root, archive, idle_before, free)
    return trees


def _classify(t: Tree, main: Tree | None, user_home: str, root: str, archive: str, idle_before: str, free) -> None:
    if t.kind == "folder":
        if _temporary(t.path, user_home):
            t.action, t.reason = "SCRATCH", "temporary or scratch folder"
        elif _agent_owned(t.path, user_home):
            t.action, t.reason = "AGENT", "an agent's own data folder"
        else:
            t.action, t.reason = "KEEP", "not a git repository: nothing to compare it against"
        return
    if _agent_owned(t.path, user_home):
        t.action, t.reason = "AGENT", "inside an agent's own folder; the agent manages it"
        return
    if t is main:
        if paths.is_within(t.path, root):
            t.action, t.reason = "MAIN", "main copy, already in place"
            return
        t.dst = free(os.path.join(root, _slug(t.name)), t)
        if paths.is_cloud_synced(t.path):
            t.action, t.reason = "DECIDE", "main copy inside a cloud-synced folder: moving it out stops syncing it"
        else:
            t.action, t.reason = "MAIN", f"main copy ({t.sessions} sessions, last used {t.last_activity or '?'})"
        return

    risks = []
    if t.unique is None:
        risks.append("could not be checked")
    if t.changed:
        risks.append(f"{t.changed} files with uncommitted changes")
    if t.kind == "clone":
        t.unique = _unique_vs(t, main) if t.unique is not None else None
        if t.unique:
            risks.append(f"{t.unique} commits found nowhere else")
        if t.stash:
            risks.append(f"{t.stash} stashed changes")
    else:
        t.unique = _unmerged(t) if t.unique is not None else None
        # a worktree's commits live in its main clone's .git: they survive the folder
        if t.unique and not (main and paths.key(t.main_root) == paths.key(main.path)):
            risks.append(f"{t.unique} unmerged commits whose clone is not the main copy")
    inside_main = main is not None and paths.is_within(t.path, main.path)
    # Gathering is a move: nothing is lost, so copies in use or holding work go into the project.
    target = (main.dst or main.path) if main is not None and main.action == "MAIN" else ""
    used = f"used on {t.last_activity}" if t.last_activity >= idle_before else f"idle since {t.last_activity or '?'}"
    detail = f"{used}; {'; '.join(risks)}" if risks else used

    if paths.is_cloud_synced(t.path):  # moving it out deletes it from the cloud, even inside its main copy
        t.action, t.reason = "DECIDE", "inside a cloud-synced folder; " + detail
    elif t.unique is None:
        t.action, t.reason = "DECIDE", detail
    elif t.last_activity >= idle_before or risks:
        if inside_main:
            t.action, t.reason = "WITH_MAIN", detail
        elif target:
            t.action, t.reason = "GATHER", detail
            t.dst = free(os.path.join(target, WORKTREES, os.path.basename(t.path.rstrip("\\/"))), t)
        elif risks:
            t.action, t.reason = "DECIDE", detail + "; no main copy to gather it into"
        else:
            t.action, t.reason = "ACTIVE", detail
    else:
        t.action = "ARCHIVE"
        t.reason = (f"idle since {t.last_activity or '?'}; everything in it is "
                    + ("in the main copy or a remote" if main else "in a remote"))
        t.dst = free(os.path.join(archive, _slug(t.name), os.path.basename(t.path.rstrip("\\/"))), t)


# ----------------------------------------------------------------------------- apply

APPLY = ("MAIN", "GATHER", "ARCHIVE")  # WITH_MAIN rides inside its main; the rest is never moved here


def moves(trees: list[Tree]) -> list[Tree]:
    """The folders apply() moves, in order: mains first, so copies gather into their new place.
    Never one in a cloud-synced folder: moving it out deletes it from the cloud."""
    return [t for a in APPLY for t in trees if t.action == a and t.dst and paths.key(t.dst) != paths.key(t.path)
            and not paths.is_cloud_synced(t.path)]


def _exclude_worktrees(project: str) -> None:
    """Keep the gathered copies out of the project's `git status`."""
    info = os.path.join(project, ".git", "info")
    if not os.path.isdir(os.path.join(project, ".git")):
        return
    os.makedirs(info, exist_ok=True)
    exclude = os.path.join(info, "exclude")
    text = open(exclude, encoding="utf-8").read() if os.path.exists(exclude) else ""
    if f"/{WORKTREES}/" not in text.split("\n"):
        with open(exclude, "a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + f"/{WORKTREES}/\n")


def apply(trees: list[Tree], user_home: str, log=print) -> list[tuple[Tree, str]]:
    """Move each folder of `moves(trees)` with `move` (journaled, undoable, junction at the old path).

    A folder moved earlier may hold a later one, so later sources follow it. Stops at the first
    failure: that move is rolled back by `move.execute`, and the ones before it stay applied.
    """
    from agentroot import move

    moved: list[tuple[str, str]] = []
    done = []
    for t in moves(trees):
        src = t.path
        for old, new in moved:
            src = paths.remap(src, old, new) or src
        if t.action == "GATHER":
            _exclude_worktrees(os.path.dirname(os.path.dirname(t.dst)))
        jid = move.execute(user_home, move.plan(user_home, src, t.dst))
        moved.append((src, t.dst))
        done.append((t, jid))
        log(f"{t.action:<8} {src} -> {t.dst}  ({jid})")
    return done


# ----------------------------------------------------------------------------- output


ORDER = ["MAIN", "WITH_MAIN", "GATHER", "ACTIVE", "DECIDE", "ARCHIVE", "AGENT", "KEEP", "SCRATCH"]


def summary(trees: list[Tree]) -> str:
    lines = [f"{len(trees)} folders, {sum(t.mb for t in trees) / 1024:.1f} GB "
             f"+ {sum(t.regen_mb for t in trees) / 1024:.1f} GB rebuildable (node_modules, .venv, caches)", ""]
    for a in ORDER:
        sel = [t for t in trees if t.action == a]
        if sel:
            lines.append(f"  {a:<10} {len(sel):>4} folders  {sum(t.mb + t.regen_mb for t in sel) / 1024:6.1f} GB")
    return "\n".join(lines)


def to_dicts(trees: list[Tree]) -> list[dict]:
    return [asdict(t) for t in sorted(trees, key=lambda t: (t.name.lower(), ORDER.index(t.action) if t.action in ORDER else 99, t.path.lower()))]
