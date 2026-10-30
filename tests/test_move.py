import hashlib
import json
import os
import shutil
import sqlite3
import subprocess

import pytest

from agentroot import catalog, move, paths

from conftest import write_jsonl

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")


def _tree_hashes(root):
    out = {}
    for dirpath, _, files in os.walk(root):
        if ".agentroot" in dirpath:
            continue
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _db(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


@windows_only
def test_remap_keeps_each_stores_spelling():
    s, d = r"C:\Users\Me\My Proj", r"C:\Projetos\my-proj"
    assert paths.remap(r"\\?\C:\Users\Me\My Proj\x", s, d) == r"\\?\C:\Projetos\my-proj\x"
    assert paths.remap(r"c:\users\me\my proj", s, d) == r"c:\projetos\my-proj"
    assert paths.remap("c:/users/me/my proj", s, d) == "c:/projetos/my-proj"
    assert paths.remap("C:/Users/Me/My Proj", s, d) == "C:/Projetos/my-proj"
    assert paths.remap("file:///c%3A/Users/Me/My%20Proj", s, d) == "file:///c%3A/Projetos/my-proj"
    assert paths.remap("file:///C:/Users/Me/My%20Proj/", s, d) == "file:///C:/Projetos/my-proj/"
    assert paths.remap(r"C:\Users\Me\My Project2", s, d) is None


def test_rewrite_json_text_only_touches_path_tokens():
    src, dst = os.path.join(os.sep, "a", "proj"), os.path.join(os.sep, "b", "proj")
    text = json.dumps({"cwd": src, "message": f"I edited {src} today", "other": src + "2"})
    new, n = move.rewrite_json_text(text, src, dst)
    data = json.loads(new)
    assert n == 1 and data["cwd"] == dst
    assert data["message"] == f"I edited {src} today" and data["other"] == src + "2"


def test_keyed_rewrite_leaves_conversation_text_alone():
    src, dst = os.path.join(os.sep, "a", "proj"), os.path.join(os.sep, "b", "proj")
    line = json.dumps({"cwd": src, "message": {"content": src}}) + "\n"
    new, n = move.rewrite_json_text(line, src, dst, ("cwd",))
    assert n == 1 and json.loads(new)["message"]["content"] == src


def test_session_text_with_unicode_line_separators_is_not_misread(machine):
    # Real Claude transcripts contain U+2028 inside strings; JSON allows it, str.splitlines() splits on it.
    home, repo = machine["home"], machine["repo"]
    f = next((home / ".claude" / "projects").glob("*/s1.jsonl"))
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"cwd": str(repo), "message": "a b\x85c"}, ensure_ascii=False) + "\n")
    p = move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo"))
    assert any(t.path == str(f) for t in p.text)


def test_claude_folder_names_follow_the_project_but_not_its_siblings(machine):
    home, repo = machine["home"], machine["repo"]
    projects = home / ".claude" / "projects"
    enc = paths.claude_project_dir(str(repo))
    # 1) a worktree's folder holding a session whose cwd is ANOTHER worktree of the same repo
    write_jsonl(projects / (enc + "--claude-worktrees-old-name") / "m1.jsonl", [{"cwd": str(machine["wt"])}])
    # 2) a sibling folder "My Repo-2" whose name starts like ours: must not be renamed
    sibling = repo.parent / "My Repo-2"
    sibling.mkdir()
    write_jsonl(projects / paths.claude_project_dir(str(sibling)) / "m2.jsonl", [{"cwd": str(sibling)}])
    p = move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo"))
    renamed = {os.path.basename(r.old) for r in p.renames}
    assert enc + "--claude-worktrees-old-name" in renamed
    assert paths.claude_project_dir(str(sibling)) not in renamed


def test_dry_run_changes_nothing(machine):
    home = machine["home"]
    before = _tree_hashes(home)
    p = move.plan(str(home), str(machine["repo"]), str(home / "Projetos" / "my-repo"))
    assert p.change_count > 0
    assert _tree_hashes(home) == before


def test_move_updates_every_agent_then_undo_restores_bytes(machine):
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    before = _tree_hashes(home)

    p = move.plan(str(home), str(repo), str(dst))
    stores = {t.store for t in p.text} | {f"{os.path.basename(e.db)}:{e.table}" for e in p.sql}
    assert {"claude session cwd", ".claude.json", "claude-desktop session", "claude-desktop git-worktrees.json",
            "codex config.toml", "state_5.sqlite:threads", "state_5.sqlite:project_roots",
            "conversation_summaries.db:conversation_summaries"} <= stores
    assert len(p.renames) == 3  # repo, feat-x worktree and the deleted worktree's session folders

    jid = move.execute(str(home), p, junction=False)
    assert dst.is_dir() and not repo.exists()
    assert move.verify(str(home), str(repo), str(dst)) == []

    # every agent now files the sessions under the new folder, in its own spelling
    cwd = _db(home / ".codex" / "state_5.sqlite", "select cwd from threads where id='t1'")[0][0]
    assert cwd.endswith("my-repo") and (cwd.startswith("\\\\?\\") or os.name != "nt")
    toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert str(dst).lower() in toml
    uris = _db(home / ".gemini" / "antigravity" / "conversation_summaries.db", "select workspace_uris from conversation_summaries")[0][0]
    assert "Projetos/my-repo" in uris and ("%3A" in uris or os.name != "nt")
    enc = paths.claude_project_dir(str(dst))
    assert (home / ".claude" / "projects" / enc / "s1.jsonl").is_file()

    scan = catalog.build(str(home))
    proj = [p for p in scan.projects if p.name == "my-repo"][0]
    assert all(paths.is_within(l.path, str(dst)) for l in proj.locations)

    move.undo(str(home), jid)
    assert repo.is_dir() and not dst.exists()
    assert _tree_hashes(home) == before


def test_failure_mid_way_rolls_back(machine, monkeypatch):
    home, repo = machine["home"], machine["repo"]
    before = _tree_hashes(home)
    p = move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo"))
    p.sql[0].old = "something else"  # simulate the app changing a row after planning
    with pytest.raises(move.MoveError):
        move.execute(str(home), p, junction=False)
    assert repo.is_dir()
    assert _tree_hashes(home) == before


def test_refuses_when_destination_exists(machine):
    (machine["home"] / "taken").mkdir()
    with pytest.raises(move.MoveError, match="already exists"):
        move.plan(str(machine["home"]), str(machine["repo"]), str(machine["home"] / "taken"))


def test_refuses_to_move_a_folder_holding_agent_data(machine):
    with pytest.raises(move.MoveError, match="agent data directory"):
        move.plan(str(machine["home"]), str(machine["home"]), str(machine["home"].parent / "elsewhere"))


def test_refuses_key_collision(machine):
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    cfg = home / ".claude.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["projects"][str(dst).replace("\\", "/")] = {"already": "used"}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(move.MoveError, match="share the key"):
        move.plan(str(home), str(repo), str(dst))


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_real_git_worktrees_survive_the_move(tmp_path):
    home = tmp_path / "home"
    repo = home / "code" / "app"
    repo.mkdir(parents=True)
    git = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    inside = repo / ".claude" / "worktrees" / "inside"
    outside = home / "elsewhere" / "outside"
    git("worktree", "add", "-q", str(inside), "-b", "inside")
    git("worktree", "add", "-q", str(outside), "-b", "outside")

    dst = home / "Projetos" / "app"
    p = move.plan(str(home), str(repo), str(dst))
    move.execute(str(home), p, junction=False)
    listing = git("worktree", "list", "--porcelain", cwd=dst)
    assert "prunable" not in listing
    assert git("status", "--porcelain", cwd=outside) == ""          # outside worktree finds the moved repo
    assert git("status", "--porcelain", cwd=dst / ".claude" / "worktrees" / "inside") == ""


@windows_only
def test_junction_left_at_old_path_and_removed_by_undo(machine):
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=True)
    assert os.path.isdir(repo) and os.path.samefile(repo, dst)
    move.undo(str(home), jid)
    assert repo.is_dir() and not os.path.islink(repo) and not dst.exists()
