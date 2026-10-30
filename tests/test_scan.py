import json
import os
import subprocess

import pytest

from agentroot import catalog, report
from agentroot.adapters import claude, codex

from conftest import TOKEN, write_jsonl


def _project(scan, name):
    matches = [p for p in scan.projects if p.name == name]
    assert len(matches) == 1, [p.name for p in scan.projects]
    return matches[0]


def test_one_project_for_all_agents(machine):
    scan = catalog.build(str(machine["home"]))
    assert scan.errors == []
    p = _project(scan, "my-repo")
    assert p.key == "github.com/acme/my-repo"
    assert p.sessions == {"claude-code": 3, "claude-desktop": 1, "codex": 2, "antigravity": 1}
    kinds = {os.path.basename(l.path): l.kind for l in p.locations}
    assert kinds == {"My Repo": "clone", "feat-x": "worktree", "deleted-one": "missing"}
    assert "1 sessions point to missing folders" in catalog.flags(p)


def test_codex_rollout_outside_the_index_is_still_found(machine):
    scan = catalog.build(str(machine["home"]))
    t2 = [s for s in scan.sessions if s.id == "t2"]
    assert len(t2) == 1 and t2[0].warnings == ("not in the app's index",)


def test_reports_never_contain_credentials(machine, tmp_path):
    scan = catalog.build(str(machine["home"]))
    for text in (report.to_json(scan), report.to_text(scan), report.to_html(scan)):
        assert TOKEN not in text
    json.loads(report.to_json(scan))


def _dir_link(src, dst):
    """A junction on Windows (what real setups use, no admin needed), a symlink elsewhere."""
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True)
        if r.returncode != 0:
            pytest.skip("cannot create a junction here")
    else:
        os.symlink(src, dst, target_is_directory=True)


def test_shared_projects_dir_is_counted_once(machine):
    # Real case: ~/.claude-corp/projects is a junction to ~/.claude/projects.
    home = machine["home"]
    (home / ".claude-corp").mkdir()
    _dir_link(home / ".claude" / "projects", home / ".claude-corp" / "projects")
    homes = claude.homes(str(home))
    corp = [h for h in homes if h.path.endswith(".claude-corp")][0]
    assert corp.note.startswith(claude.SHARED_PREFIX)
    scan = catalog.build(str(home))
    assert sum(1 for s in scan.sessions if s.agent == "claude-code") == 3


def test_claude_session_filed_under_another_folder_is_flagged(machine):
    home, repo = machine["home"], machine["repo"]
    write_jsonl(home / ".claude" / "projects" / "C--somewhere-else" / "s9.jsonl", [{"cwd": str(repo)}])
    scan = catalog.build(str(home))
    s9 = [s for s in scan.sessions if s.id == "s9"][0]
    assert s9.warnings == ("filed under C--somewhere-else",)


@pytest.mark.skipif(codex._zstd is None, reason="needs Python 3.14 compression.zstd")
def test_codex_compressed_rollouts_are_read(machine):
    path = machine["home"] / ".codex" / "sessions" / "2026" / "10" / "01" / "rollout-x-t3.jsonl.zst"
    path.parent.mkdir(parents=True)
    with codex._zstd.open(path, "wb") as f:
        f.write((json.dumps({"type": "session_meta", "payload": {"id": "t3", "cwd": str(machine["repo"])}}) + "\n").encode())
    scan = catalog.build(str(machine["home"]))
    assert any(s.id == "t3" for s in scan.sessions)


def test_scan_does_not_modify_agent_data(machine):
    home = machine["home"]
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    catalog.build(str(home))
    after = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    assert before == after
