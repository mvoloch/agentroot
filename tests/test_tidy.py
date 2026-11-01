import datetime as dt
import os
import shutil
import subprocess

import pytest

from agentroot import tidy

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")
LATER = dt.date(2099, 1, 1)  # everything is idle by then


def git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def repo(path, remote=None, commits=1):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for i in range(commits):
        (path / f"f{i}.txt").write_text(f"{path} {i}")  # distinct content: two repos made in one second must differ
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", f"c{i}")
    if remote:
        git(path, "remote", "add", "origin", remote)
        git(path, "update-ref", "refs/remotes/origin/main", "HEAD")  # as if pushed
    return path


def clone(src, dst, remote=None):
    dst.parent.mkdir(parents=True, exist_ok=True)
    git(src.parent, "clone", "-q", str(src), str(dst))
    if remote:
        git(dst, "remote", "set-url", "origin", remote)
    return dst


def run(home, today=LATER):
    root = home / "Projetos"
    root.mkdir(exist_ok=True)
    trees = tidy.survey(str(home))
    tidy.propose(trees, str(home), str(root), today)
    return {os.path.relpath(t.path, home): t for t in trees}


URL = "https://github.com/acme/app.git"


def test_copies_are_grouped_and_the_main_copy_is_outside_conversation_folders(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    clone(main, home / "Documents" / "Codex" / "2026-09-01" / "chat" / "app", URL)
    out = run(home)
    assert out[os.path.join("code", "app")].action == "MAIN"
    assert out[os.path.join("code", "app")].dst == str(home / "Projetos" / "app")
    copy = out[os.path.join("Documents", "Codex", "2026-09-01", "chat", "app")]
    assert copy.action == "ARCHIVE" and copy.unique == 0
    assert copy.dst.startswith(str(home / "Projetos" / "_arquivo" / "2099-01-01"))


def test_a_copy_with_commits_found_nowhere_else_is_gathered_into_the_project(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    copy = clone(main, home / "old" / "app-copy", URL)
    (copy / "new.txt").write_text("x")
    git(copy, "add", ".")
    git(copy, "commit", "-q", "-m", "only here")
    t = run(home)[os.path.join("old", "app-copy")]
    assert t.action == "GATHER" and t.unique == 1 and "1 commits found nowhere else" in t.reason
    assert t.dst == str(home / "Projetos" / "app" / ".worktrees" / "app-copy")


def test_a_copy_in_use_elsewhere_is_gathered_too(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    clone(main, home / "codex-work" / "app-fix", URL)
    t = run(home, dt.date.today())[os.path.join("codex-work", "app-fix")]
    assert t.action == "GATHER" and t.dst == str(home / "Projetos" / "app" / ".worktrees" / "app-fix")


def test_a_copy_cloned_from_a_local_path_still_finds_its_project(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    copy = clone(main, home / "Documents" / "Codex" / "2026-10-24" / "chat" / "checkouts" / "app")  # origin = local path
    (copy / "fix.txt").write_text("x")
    git(copy, "add", ".")
    git(copy, "commit", "-q", "-m", "fix")
    t = run(home, dt.date.today())[os.path.join("Documents", "Codex", "2026-10-24", "chat", "checkouts", "app")]
    assert t.action == "GATHER" and t.dst == str(home / "Projetos" / "app" / ".worktrees" / "app")


def test_a_shallow_copy_finds_its_project_by_the_commit_where_it_was_cut(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL, commits=3)
    dst = home / "Documents" / "Codex" / "2026-10-24" / "chat" / "checkouts" / "app"
    dst.parent.mkdir(parents=True)
    git(dst.parent, "clone", "-q", "--depth", "1", main.as_uri(), str(dst))
    git(dst, "remote", "remove", "origin")
    t = run(home, dt.date.today())[os.path.join("Documents", "Codex", "2026-10-24", "chat", "checkouts", "app")]
    assert t.shallow and t.action == "GATHER" and t.dst == str(home / "Projetos" / "app" / ".worktrees" / "app")


def test_uncommitted_changes_block_archiving_but_untracked_files_are_listed(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    a = clone(main, home / "old" / "a", URL)
    (a / "f0.txt").write_text("changed")
    b = clone(main, home / "old" / "b", URL)
    (b / "notes.md").write_text("mine")
    out = run(home)
    assert out[os.path.join("old", "a")].action == "GATHER"
    t = out[os.path.join("old", "b")]
    assert t.action == "ARCHIVE" and t.untracked == ["notes.md"]


def test_worktrees_commits_live_in_the_main_clone(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    wt = main / ".claude" / "worktrees" / "task"
    git(main, "worktree", "add", "-q", str(wt), "-b", "task")
    (wt / "x.txt").write_text("x")
    git(wt, "add", ".")
    git(wt, "commit", "-q", "-m", "unmerged")
    dirty = main / ".claude" / "worktrees" / "dirty"
    git(main, "worktree", "add", "-q", str(dirty), "-b", "dirty")
    (dirty / "f0.txt").write_text("changed")
    out = run(home)
    task = out[os.path.join("code", "app", ".claude", "worktrees", "task")]
    assert task.action == "ARCHIVE" and task.unique == 1  # the branch stays in code/app/.git
    assert out[os.path.join("code", "app", ".claude", "worktrees", "dirty")].action == "WITH_MAIN"
    # still in use: it moves with the main copy
    assert run(home, dt.date.today())[os.path.join("code", "app", ".claude", "worktrees", "task")].action == "WITH_MAIN"


def test_local_repositories_are_grouped_by_their_first_commit(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "tool")
    clone(main, home / "Documents" / "Codex" / "2026-09-01" / "x" / "tool")
    git(home / "Documents" / "Codex" / "2026-09-01" / "x" / "tool", "remote", "remove", "origin")
    out = run(home)
    a, b = out[os.path.join("code", "tool")], out[os.path.join("Documents", "Codex", "2026-09-01", "x", "tool")]
    assert a.group == b.group and a.group.startswith("root:")
    assert a.action == "MAIN" and b.action == "ARCHIVE"


def test_agent_folders_and_cloud_folders_are_never_moved_automatically(tmp_path):
    home = tmp_path / "home"
    repo(home / ".codex" / "worktrees" / "ab12" / "app", URL)
    repo(home / "OneDrive" / "proj", "https://github.com/acme/proj.git")
    out = run(home)
    assert out[os.path.join(".codex", "worktrees", "ab12", "app")].action == "AGENT"
    t = out[os.path.join("OneDrive", "proj")]
    assert t.action == "DECIDE" and "cloud" in t.reason and t.dst == str(home / "Projetos" / "proj")


def test_a_plain_folder_does_not_hide_the_repositories_inside_it(tmp_path):
    # "Claude Projects" is a folder agents worked in (so it is an entry) and holds the real clone.
    home = tmp_path / "home"
    repo(home / "Claude Projects" / "app", URL)
    clone(home / "Claude Projects" / "app", home / "elsewhere" / "app-fix", URL)
    root = home / "Projetos"
    root.mkdir()
    trees = tidy.survey(str(home))
    container = tidy.Tree(str(home / "Claude Projects"), "folder", group="path:x", name="Claude Projects", sessions=20)
    trees.append(container)
    by = {os.path.relpath(t.path, home): t for t in trees}
    by[os.path.join("Claude Projects", "app")].sessions = 5
    tidy.propose(trees, str(home), str(root), LATER)
    assert by[os.path.join("Claude Projects", "app")].action == "MAIN"
    assert by[os.path.join("elsewhere", "app-fix")].action == "ARCHIVE"
    assert container.action == "KEEP"


def test_nothing_inside_a_cloud_folder_is_moved_even_inside_its_main_copy(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "OneDrive" / "proj", URL)
    wt = main / ".claude" / "worktrees" / "idle"
    git(main, "worktree", "add", "-q", str(wt), "-b", "idle")
    trees = list(run(home).values())
    t = next(t for t in trees if t.path.endswith("idle"))
    assert t.action == "DECIDE" and "cloud" in t.reason
    t.action, t.dst = "ARCHIVE", str(home / "Projetos" / "x")  # even if a stale proposal says so
    assert t not in tidy.moves(trees)


def test_plugin_clones_inside_dot_claude_belong_to_the_agent(tmp_path):
    home = tmp_path / "home"
    repo(home / "Desktop" / "backup" / ".claude" / "plugins" / "marketplaces" / "x", "https://github.com/acme/x.git")
    assert run(home)[os.path.join("Desktop", "backup", ".claude", "plugins", "marketplaces", "x")].action == "AGENT"


def test_two_projects_with_one_name_get_distinct_destinations(tmp_path):
    home = tmp_path / "home"
    repo(home / "a" / "app", "https://github.com/acme/app.git")
    repo(home / "b" / "app", "https://github.com/other/app.git")
    (home / "Projetos").mkdir()
    (home / "Projetos" / "app").mkdir()  # already taken by something else
    out = run(home)
    dsts = {out[os.path.join("a", "app")].dst, out[os.path.join("b", "app")].dst}
    assert dsts == {str(home / "Projetos" / "app-2"), str(home / "Projetos" / "app-3")}


def test_apply_moves_mains_then_gathers_then_archives(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    wt = main / ".claude" / "worktrees" / "old-task"
    git(main, "worktree", "add", "-q", str(wt), "-b", "old-task")  # idle, nested: archived out of the moved main
    copy = clone(main, home / "codex-work" / "app-fix", URL)
    (copy / "f0.txt").write_text("work in progress")
    root = home / "Projetos"
    root.mkdir()
    trees = tidy.survey(str(home))
    tidy.propose(trees, str(home), str(root), LATER)
    by = {os.path.relpath(t.path, home): t.action for t in trees}
    assert by[os.path.join("code", "app")] == "MAIN" and by[os.path.join("codex-work", "app-fix")] == "GATHER"
    assert by[os.path.join("code", "app", ".claude", "worktrees", "old-task")] == "ARCHIVE"

    done = tidy.apply(trees, str(home), log=lambda s: None)
    assert [t.action for t, _ in done] == ["MAIN", "GATHER", "ARCHIVE"]
    assert (root / "app" / ".git").is_dir()
    gathered = root / "app" / ".worktrees" / "app-fix"
    assert (gathered / "f0.txt").read_text() == "work in progress"
    assert "/.worktrees/" in (root / "app" / ".git" / "info" / "exclude").read_text().split("\n")
    assert "app-fix" not in git(root / "app", "status", "--porcelain")
    archived = root / "_arquivo" / "2099-01-01" / "app" / "old-task"
    assert (archived / ".git").is_file()
    assert git(archived, "rev-parse", "--abbrev-ref", "HEAD").strip() == "old-task"  # worktree still linked
    old = root / "app" / ".claude" / "worktrees" / "old-task"  # a junction at the old path, as every move leaves
    assert os.path.realpath(old).lower() == os.path.realpath(archived).lower()


def test_survey_writes_nothing(tmp_path):
    home = tmp_path / "home"
    main = repo(home / "code" / "app", URL)
    clone(main, home / "old" / "app", URL)

    def snapshot():
        out = {}
        for dp, _, fns in os.walk(home):
            for f in fns:
                p = os.path.join(dp, f)
                out[p] = (os.path.getsize(p), os.path.getmtime(p))
        return out

    before = snapshot()
    run(home)
    assert snapshot() == before
