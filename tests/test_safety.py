"""Regressions from the data-loss audit: each test reproduces a way a move or an undo used to lose data."""
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time

import pytest

from agentroot import cli, move, paths
from agentroot.adapters import claude

from conftest import write_jsonl
from test_move import _db, _tree_hashes

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows file locking")


def _journal(home, jid):
    with open(home / ".agentroot" / "journal" / jid / "journal.json", encoding="utf-8") as f:
        return json.load(f)


@windows_only
def test_locked_file_in_the_project_leaves_everything_in_place(machine):
    # A terminal or editor inside the project: a rename fails. It must not fall back to copy + delete.
    home, repo = machine["home"], machine["repo"]
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    before = _tree_hashes(home)
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=repo / "src")
    try:
        time.sleep(0.5)
        with pytest.raises(OSError):
            move.execute(str(home), move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo")), junction=False)
    finally:
        holder.kill()
        holder.wait()
    assert not (home / "Projetos" / "my-repo").exists()
    assert _tree_hashes(home) == before
    jid = os.listdir(home / ".agentroot" / "journal")[0]
    assert _journal(home, jid)["state"] == "rolled back"


@windows_only
def test_undo_blocked_by_an_open_terminal_changes_nothing_and_can_be_retried(machine):
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=True)
    after = _tree_hashes(dst)
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=dst / ".git")
    try:
        time.sleep(0.5)
        with pytest.raises(move.MoveError, match="close anything open"):
            move.undo(str(home), jid)
        # still fully in the moved state: folder, junction and every registry agree
        assert _tree_hashes(dst) == after and os.path.samefile(repo, dst)
        assert _journal(home, jid)["state"] == "applied"
        assert move.verify(str(home), str(repo), str(dst)) == []
    finally:
        holder.kill()
        holder.wait()
    move.undo(str(home), jid)  # retried after closing the terminal
    assert repo.is_dir() and not os.path.islink(repo) and not dst.exists()
    assert move.verify(str(home), str(dst), str(repo)) == []


def test_undo_after_a_day_of_work_keeps_the_new_work(machine):
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=os.name == "nt")
    # the user resumes a session in the new folder, Claude registers another project, Codex a new thread
    session = home / ".claude" / "projects" / paths.claude_project_dir(str(dst)) / "s1.jsonl"
    with open(session, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "cwd": str(dst), "message": "DAY-2 TURN"}) + "\n")
    cfg = home / ".claude.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["projects"]["C:/other/app"] = {}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    con = sqlite3.connect(home / ".codex" / "state_5.sqlite")
    con.execute("insert into threads values ('t-new', 'C:\\other\\app', 2, '', 0)")
    con.commit()
    con.close()

    data = move.undo(str(home), jid)
    assert data["state"].startswith("reversed by")
    assert repo.is_dir() and not dst.exists()
    back = home / ".claude" / "projects" / paths.claude_project_dir(str(repo)) / "s1.jsonl"
    assert "DAY-2 TURN" in back.read_text(encoding="utf-8")
    assert "C:/other/app" in json.loads(cfg.read_text(encoding="utf-8"))["projects"]
    assert _db(home / ".codex" / "state_5.sqlite", "select count(*) from threads where id='t-new'")[0][0] == 1
    assert move.verify(str(home), str(dst), str(repo)) == []


def test_undo_sees_a_new_turn_in_a_renamed_session_folder(machine):
    # The only change is one line appended to a session file that now lives in the renamed folder.
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=False)
    session = home / ".claude" / "projects" / paths.claude_project_dir(str(dst)) / "s1.jsonl"
    with open(session, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "cwd": str(dst), "message": "DAY-2 TURN"}) + "\n")
    assert move.undo(str(home), jid)["state"].startswith("reversed by")
    back = home / ".claude" / "projects" / paths.claude_project_dir(str(repo)) / "s1.jsonl"
    assert "DAY-2 TURN" in back.read_text(encoding="utf-8")


def test_undo_when_claude_recreated_the_old_session_folder(machine):
    # Opening the project through the junction makes Claude create projects/<old name>/ again.
    home, repo = machine["home"], machine["repo"]
    dst = home / "Projetos" / "my-repo"
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=False)
    write_jsonl(home / ".claude" / "projects" / paths.claude_project_dir(str(repo)) / "new.jsonl", [{"cwd": str(repo)}])
    move.undo(str(home), jid)
    folder = home / ".claude" / "projects" / paths.claude_project_dir(str(repo))
    assert {"s1.jsonl", "new.jsonl"} <= set(os.listdir(folder))
    assert repo.is_dir() and not dst.exists()


@windows_only
def test_rollback_restores_every_file_even_when_one_cannot_be_written(machine):
    home, repo = machine["home"], machine["repo"]
    toml = home / ".codex" / "config.toml"
    os.chmod(toml, stat.S_IREAD)
    before = _tree_hashes(home)
    try:
        with pytest.raises(OSError):
            move.execute(str(home), move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo")), junction=False)
        assert _tree_hashes(home) == before
        assert not list(home.rglob("*.agentroot-tmp"))
    finally:
        os.chmod(toml, stat.S_IREAD | stat.S_IWRITE)


def test_refuses_session_folder_renames_that_chain(machine):
    home, repo = machine["home"], machine["repo"]
    sub = repo / "v2"
    sub.mkdir()
    write_jsonl(home / ".claude" / "projects" / paths.claude_project_dir(str(sub)) / "v2.jsonl", [{"cwd": str(sub)}])
    with pytest.raises(move.MoveError, match="collide"):
        move.plan(str(home), str(repo), str(repo.parent / "My Repo-v2"))


def test_relative_paths_are_made_absolute(machine, monkeypatch):
    home, repo = machine["home"], machine["repo"]
    monkeypatch.chdir(repo.parent)
    p = move.plan(str(home), "My Repo", os.path.join("..", "Projetos", "b"))
    assert p.src == str(repo) and p.dst == str(home / "Projetos" / "b")
    assert any(t.store == ".claude.json" for t in p.text)


def test_blob_columns_are_rewritten(machine):
    home, repo = machine["home"], machine["repo"]
    db = home / "AppData" / "Roaming" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table ItemTable (key text unique, value blob)")
    con.execute("insert into ItemTable values ('k', ?)", (json.dumps({"folder": str(repo)}).encode(),))
    con.commit()
    con.close()
    dst = home / "Projetos" / "x"
    move.execute(str(home), move.plan(str(home), str(repo), str(dst)), junction=False)
    value = _db(db, "select value from ItemTable")[0][0]
    assert isinstance(value, bytes) and json.loads(value)["folder"] == str(dst)


def test_home_override_never_reaches_the_real_profile(machine, monkeypatch, tmp_path):
    # %APPDATA% (or CODEX_HOME) set to the real profile must not leak into `--home <copy>`.
    real = tmp_path / "real-appdata"
    (real / "Claude" / "claude-code-sessions").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(real))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "real-codex"))
    found = [h.path for h in claude.homes(str(machine["home"]))]
    assert not any(str(real) in h for h in found)
    assert any(h.endswith(os.path.join("AppData", "Roaming", "Claude")) for h in found)
    from agentroot.adapters import codex
    assert [h.path for h in codex.homes(str(machine["home"]))] == [str(machine["home"] / ".codex")]


def test_running_agent_check_sees_npm_installs_and_fails_closed(monkeypatch):
    lines = {
        "nt": "node.exe\t\"C:\\node.exe\" C:\\npm\\node_modules\\@google\\gemini-cli\\bundle\\gemini.js\n"
              "node.exe\tnode server.js\nexplorer.exe\tC:\\Windows\\explorer.exe\n",
        "posix": "/usr/bin/node /usr/lib/node_modules/@google/gemini-cli/bundle/gemini.js\nnode server.js\n",
    }["nt" if os.name == "nt" else "posix"]
    run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=lines, stderr="")
    monkeypatch.setattr(move.subprocess, "run", run)
    assert move.running_agents() == ["node.exe" if os.name == "nt" else "node"]
    monkeypatch.setattr(move.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=""))
    assert move.running_agents() == ["(could not list processes)"]


def test_undo_twice_is_refused_and_a_failed_move_cannot_be_undone(machine):
    home, repo = machine["home"], machine["repo"]
    jid = move.execute(str(home), move.plan(str(home), str(repo), str(home / "Projetos" / "my-repo")), junction=False)
    move.undo(str(home), jid)
    with pytest.raises(move.MoveError, match="only an applied move"):
        move.undo(str(home), jid)
    with pytest.raises(move.MoveError, match="no move to undo"):
        move.undo(str(home))


def test_cli_undo_refuses_while_an_agent_runs(machine, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_real_home", lambda h: True)
    monkeypatch.setattr(move, "running_agents", lambda: ["Codex.exe"])
    assert cli.main(["undo", "--home", str(machine["home"])]) == 2
    assert "Codex.exe" in capsys.readouterr().out
