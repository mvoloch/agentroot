import os

import pytest

from agentroot import paths

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")


@windows_only
def test_every_agents_spelling_of_one_folder_has_the_same_key():
    forms = [
        r"C:\Users\Me\My Proj",                         # Claude Code cwd
        "C:/Users/Me/My Proj",                           # ~/.claude.json key
        r"\\?\C:\Users\Me\My Proj",                     # Codex threads.cwd
        r"c:\users\me\my proj",                          # Codex config.toml, Gemini projects.json
        "file:///c%3A/Users/Me/My%20Proj",               # Antigravity workspace_uris
        "file:///C:/Users/Me/My%20Proj/",                # agy CLI
    ]
    assert len({paths.key(f) for f in forms}) == 1
    assert paths.display("file:///c%3A/Users/Me/My%20Proj") == r"C:\Users\Me\My Proj"


@windows_only
def test_claude_project_dir_matches_what_claude_code_writes():
    # Same shapes as folder names observed under a real ~/.claude/projects (names changed).
    cwd = r"C:\Users\me\Claude Projects\app\voice\.claude\worktrees\new-logo-c5c507"
    assert paths.claude_project_dir(cwd) == "C--Users-me-Claude-Projects-app-voice--claude-worktrees-new-logo-c5c507"
    assert paths.claude_project_dir(r"C:\Users\me\OneDrive - Acme Shipping S.A\results") == \
        "C--Users-me-OneDrive---Acme-Shipping-S-A-results"


@windows_only
def test_is_within_respects_folder_boundaries():
    assert paths.is_within(r"C:\a\proj\sub", r"C:\a\proj")
    assert not paths.is_within(r"C:\a\project2", r"C:\a\proj")


@windows_only
def test_temporary_and_cloud_detection():
    assert paths.is_temporary(r"C:\Users\me\AppData\Local\Temp\claude\x")
    assert paths.is_temporary(r"C:\Users\me\AppData\Roaming\Claude\scratch-workspaces\a\b")
    assert not paths.is_temporary(r"C:\Projetos\x")
    assert paths.is_cloud_synced(r"C:\Users\me\OneDrive - Acme\Claude Projects\survey")


def test_not_a_path_is_empty():
    assert paths.display("") == ""
    assert paths.display("   ") == ""
