import json
import os
import sqlite3

import pytest

TOKEN = "ghp_SECRETSECRETSECRET"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Adapters read APPDATA, LOCALAPPDATA, CODEX_HOME...: point them all inside tmp_path."""
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "home" / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "home" / "AppData" / "Local"))


def make_repo(path, remote=None):
    """A clone as git leaves it on disk (no git binary needed)."""
    git = path / ".git"
    git.mkdir(parents=True)
    cfg = "[core]\n\trepositoryformatversion = 0\n"
    if remote:
        cfg += f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
    (git / "config").write_text(cfg, encoding="utf-8")
    return path


def make_worktree(main, path, name):
    admin = main / ".git" / "worktrees" / name
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    path.mkdir(parents=True)
    (path / ".git").write_text(f"gitdir: {admin.as_posix()}\n", encoding="utf-8")
    return path


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def sqlite_db(path, ddl, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for stmt in ddl:
        con.execute(stmt)
    for sql, values in rows:
        con.executemany(sql, values)
    con.commit()
    con.close()


@pytest.fixture
def machine(tmp_path):
    """A user home with one repo used by all three agents, recorded in each agent's own format."""
    home = tmp_path / "home"
    repo = make_repo(home / "code" / "My Repo", f"https://alice:{TOKEN}@github.com/acme/My-Repo.git")
    wt = make_worktree(repo, repo / ".claude" / "worktrees" / "feat-x", "feat-x")
    gone = repo / ".claude" / "worktrees" / "deleted-one"
    win = os.name == "nt"

    # Claude Code: projects/<encoded>/<id>.jsonl, cwd on the lines
    from agentroot.paths import claude_project_dir
    for sid, cwd in (("s1", repo), ("s2", wt), ("s3", gone)):
        write_jsonl(home / ".claude" / "projects" / claude_project_dir(str(cwd)) / f"{sid}.jsonl",
                    [{"type": "summary"}, {"type": "user", "cwd": str(cwd), "sessionId": sid}])
    (home / ".claude.json").write_text(json.dumps({"projects": {str(repo).replace("\\", "/"): {}}}), encoding="utf-8")

    # Claude desktop
    desk = home / "AppData" / "Roaming" / "Claude"
    (desk / "claude-code-sessions" / "a" / "b").mkdir(parents=True)
    (desk / "claude-code-sessions" / "a" / "b" / "local_1.json").write_text(
        json.dumps({"sessionId": "local_1", "cwd": str(wt), "originCwd": str(repo), "worktreePath": str(wt)}), encoding="utf-8")
    (desk / "git-worktrees.json").write_text(json.dumps({"worktrees": {"feat-x": {"path": str(wt), "baseRepo": str(repo)}}}), encoding="utf-8")

    # Codex: threads.cwd with the \\?\ prefix, lower-cased trust key, one rollout outside the index
    codex = home / ".codex"
    extended = ("\\\\?\\" + str(repo)) if win else str(repo)
    sqlite_db(codex / "state_5.sqlite",
              ["create table threads (id text primary key, cwd text, updated_at integer, git_origin_url text, archived integer)",
               "create table project_roots (project_id text, position integer, path text)"],
              [("insert into threads values (?,?,?,?,?)", [("t1", extended, 1761800000, f"https://x:{TOKEN}@github.com/acme/My-Repo.git", 0)]),
               ("insert into project_roots values (?,?,?)", [("p1", 0, str(repo))])])
    (codex / "config.toml").write_text(f"[projects.'{str(repo).lower()}']\ntrust_level = \"trusted\"\n", encoding="utf-8")
    write_jsonl(codex / "sessions" / "2026" / "10" / "30" / "rollout-2026-10-30T09-00-00-t2.jsonl",
                [{"type": "session_meta", "payload": {"id": "t2", "cwd": str(repo)}}])

    # Antigravity: file:/// URI with percent-encoding
    uri = "file:///" + str(repo).replace("\\", "/").replace(":", "%3A").replace(" ", "%20")
    sqlite_db(home / ".gemini" / "antigravity" / "conversation_summaries.db",
              ["create table conversation_summaries (conversation_id text, workspace_uris text, project_id text, last_modified_time text)"],
              [("insert into conversation_summaries values (?,?,?,?)", [("c1", json.dumps([uri]), "proj-1", "2026-10-30T10:00:00Z")])])
    return {"home": home, "repo": repo, "wt": wt, "gone": gone}
