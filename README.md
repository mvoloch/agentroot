# agentroot

**One folder per project for Claude Code, Codex and Antigravity.**

Every AI coding agent keeps its own record of where your projects are: Claude Code names a
session folder after the path, Codex writes `\\?\C:\...` into SQLite, Antigravity stores
`file:///c%3A/...` URIs, and each one creates worktrees and scratch folders wherever it likes.
After a few months the same repository lives in a dozen places, and moving any of them breaks
`resume` in every agent at once.

`agentroot` reads all of them and shows you, per project, every folder and every session each
agent has, so you can bring the mess down to `~/Projects/<project>` without losing history.

> **Status: early.** `scan` is read-only and stable. `move` works and has been rehearsed on a
> copy of real data (169,000 path rewrites across all four agents, verified, undone byte for
> byte), but it rewrites private formats of tools that change often: back up, close every
> agent, and start with a small project.

## What it finds

| Agent | Homes it discovers |
|---|---|
| Claude Code | `~/.claude`, every `~/.claude-*` config dir (`CLAUDE_CONFIG_DIR`), shared `projects/` through junctions counted once |
| Claude desktop | `%APPDATA%\Claude`, `~/.claude-enterprise` (Team), macOS/Linux equivalents |
| Codex | `$CODEX_HOME` or `~/.codex`: both state databases, compressed rollouts, desktop catalog, global state, trust list, worktrees (including the Microsoft Store location) |
| Antigravity / Gemini CLI | `~/.gemini/antigravity*`, project configs, `projects.json`, `.project_root` markers, trust lists, `%APPDATA%\Antigravity` workspace storage |

Then it groups everything by **git remote** (credentials stripped), so `my_app`,
`my-app-old-copy` and a Codex worktree of the same repo show up as one project, and flags:

- clones of the same repo in several places
- worktrees, and sessions that point at worktrees you already deleted
- git repositories inside OneDrive/Dropbox/Google Drive/iCloud
- projects that only exist in temporary or scratch folders

## Use

Requires Python 3.11+ (3.14+ also reads Codex's compressed rollouts). No dependencies.

```bash
python -m pip install git+https://github.com/<owner>/agentroot   # not published yet
agentroot homes                      # which agent data directories exist on this machine
agentroot scan                       # projects, folders and sessions per agent
agentroot scan --html report.html --json catalog.json

agentroot move C:\code\my-app C:\Projetos\my-app          # dry run: prints every change
agentroot move C:\code\my-app C:\Projetos\my-app --yes    # apply (refuses while any agent runs)
agentroot undo                                            # reverse the last move
agentroot journal                                         # list past moves
```

`move` moves the folder, renames Claude Code's session folders, rewrites the path in every
registry of every agent in that store's own spelling, runs `git worktree repair`, leaves a
junction at the old path, verifies that nothing still points there, and journals each step
under `~/.agentroot/journal/` with a backup of every file it touched. If any step fails,
everything is rolled back. Conversation bodies are never rewritten
([why](docs/RISKS.md)). `--no-move` only rewrites references, for a folder you already moved.

From a checkout: `PYTHONPATH=src python -m agentroot scan`.

## Safety

- `scan` never writes to an agent's files. SQLite databases are copied (with `-wal`/`-shm`) to a
  temp dir and read there, so a running agent is never locked or disturbed. A test asserts that
  no file in a fake agent home changes during a scan.
- It never opens credential files and strips `user:token@` from every git URL before printing.
- Reports contain paths, counts and dates, not conversation text.

## Docs

- [docs/STORAGE.md](docs/STORAGE.md): where each agent records a project path, with evidence.
- [docs/RISKS.md](docs/RISKS.md): what breaks when a folder moves, and the rules `apply` follows.

## Prior art

claude-repath, [claudepath](https://pypi.org/project/claudepath/) and
[claude-mover](https://github.com/automatix/claude-mover) move Claude Code projects;
[repo-sessions](https://github.com/firish/repo-sessions) syncs Claude and Codex sessions through
git; cass (coding_agent_session_search) searches sessions across agents.
`agentroot` exists because none of them covers Codex's and Antigravity's registries or groups the
three agents by project.

## License

MIT
