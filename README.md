# agentroot

**One folder per project for Claude Code, Codex and Antigravity.**

Every AI coding agent keeps its own record of where your projects are: Claude Code names a
session folder after the path, Codex writes `\\?\C:\...` into SQLite, Antigravity stores
`file:///c%3A/...` URIs, and each one creates worktrees and scratch folders wherever it likes.
After a few months the same repository lives in a dozen places, and moving any of them breaks
`resume` in every agent at once.

`agentroot` reads all of them and shows you, per project, every folder and every session each
agent has, so you can bring the mess down to `~/Projects/<project>` without losing history.

Free and open source (MIT), and it will stay that way. No telemetry, no network access, no
dependencies.

> **Status: alpha, tested on Windows only.** `scan` is read-only and safe to try. `move`, `undo`,
> `tidy` and `identity` work on a real machine but rewrite private, undocumented formats of tools
> that change often. Close every agent, back up your profile, and start with a small project.
> Read [what was tested](#what-was-tested) before you rely on it.

## What was tested

Everything below was run by one person, on Windows, on their own data. Nothing else has been
tested yet.

| | Tested |
|---|---|
| Operating system | Windows 11 Pro (Insider Preview, build 26220) |
| Machines | Two Windows PCs. One profile was copied from the first to the second, so the copy-to-a-new-machine case is Windows to Windows only. |
| Python | 3.14.7 (3.12 also installed; 3.11 is the declared minimum) |
| Git | 2.55.0.windows.5 |
| Claude | Two installations side by side, a personal account and a Team account: Claude Code 2.1.312 with three config directories (`~/.claude`, two `~/.claude-*`), and the Claude desktop app 4.4212 (`%APPDATA%\Claude`, `~/.claude-enterprise`) |
| OpenAI | Codex CLI 0.161.0 and the Codex desktop app 26.1027 from the Microsoft Store (the ChatGPT desktop app's coding agent) |
| Google | Antigravity 2.28.2, Antigravity IDE 2.5.5, and Gemini CLI 0.59.0 through the shared `~/.gemini` registries |

The versions are the ones installed on 1 November 2026. The large `move` rehearsal ran a few
days earlier on the first machine, with the versions that were current in late October 2026.

What that rehearsal covered:
- 169,098 changes for one project across Claude Code, the Claude app, Codex and Antigravity;
- integrity checks: every SQLite database passed `quick_check`, and every JSON file and all
  215,839 JSONL lines parsed;
- `undo`, with zero byte differences;
- a second run with new work appended after the move, where `undo` kept that work.

The tool was then used for real: 112 project moves to reorganize the second machine.

**Not tested at all:**
- macOS and Linux. Their paths are in the code, but nothing has run there;
- copying a profile between different operating systems;
- other agents (Cursor, Windsurf, Copilot and so on): they are not read;
- other versions of the apps above. A newer release may change its storage. `agentroot` refuses
  to write a format it does not recognize, but it cannot know about a change it has never seen.

If you run it on anything else, please [open an issue](../../issues) with what happened, even
when it worked.

## What it finds

| Agent | Homes it discovers |
|---|---|
| Claude Code | `~/.claude`, every `~/.claude-*` config dir (`CLAUDE_CONFIG_DIR`), shared `projects/` through junctions counted once |
| Claude desktop | `%APPDATA%\Claude`, `~/.claude-enterprise` (Team); macOS/Linux equivalents untested |
| Codex | `$CODEX_HOME` or `~/.codex`: both state databases, compressed rollouts, desktop catalog, global state, trust list, worktrees (including the Microsoft Store location) |
| Antigravity / Gemini CLI | `~/.gemini/antigravity*`, project configs, `projects.json`, `.project_root` markers, trust lists, `%APPDATA%\Antigravity` workspace storage |

Then it groups everything by **git remote** (credentials stripped), so `my_app`,
`my-app-old-copy` and a Codex worktree of the same repo show up as one project, and flags:

- clones of the same repo in several places
- worktrees, and sessions that point at worktrees you already deleted
- git repositories inside OneDrive/Dropbox/Google Drive/iCloud
- projects that only exist in temporary or scratch folders

## Install

Requires Python 3.11+ (3.14+ also reads Codex's compressed rollouts) and git.

```bash
python -m pip install git+https://github.com/mvoloch/agentroot@v0.1.0
```

Or from a checkout, without installing: `PYTHONPATH=src python -m agentroot scan`.

## Use

```bash
agentroot homes                      # which agent data directories exist on this machine
agentroot scan                       # projects, folders and sessions per agent
agentroot scan --html report.html --json catalog.json

agentroot move C:\code\my-app C:\Projetos\my-app          # dry run: prints every change
agentroot move C:\code\my-app C:\Projetos\my-app --yes    # apply (refuses while any agent runs)
agentroot verify C:\code\my-app C:\Projetos\my-app        # does anything still point at the old path?
agentroot undo                                            # reverse the last move
agentroot journal                                         # list past moves
agentroot identity                                        # after copying a profile to a new machine: what still names the old one
```

`move` does several things:
- renames the folder (same drive only: a rename is all or nothing);
- renames Claude Code's session folders;
- rewrites the path in every registry of every agent, in that store's own spelling;
- runs `git worktree repair`;
- leaves a junction at the old path (`--no-junction` to skip);
- verifies that nothing still points at the old path;
- journals each step under `~/.agentroot/journal/`, with a backup of every file it touched.

If any step fails, every step is reversed. Conversation bodies are never rewritten
([why](docs/RISKS.md)). `--no-move` only rewrites references, for a folder you already moved
yourself (for example to another drive).

`agentroot tidy --root C:\Projetos --json proposal.json` finds every git working tree on disk
(not only the ones agents know about) and proposes one action per folder:
- the project's main copy moves to the root;
- idle copies whose every commit is already in the main copy or a remote go to `_arquivo`;
- anything holding work that exists nowhere else is left for you to decide.

It never deletes and never moves anything itself.

`undo` puts the backups back byte for byte only if nothing has changed since the move. If an
agent has written since then, restoring old bytes would erase that, so instead it moves the
project back and rewrites every reference again.

`agentroot identity` is for after you copy a profile to a new machine. A copied Codex profile
keeps the old machine's remote-control enrollment, and copied Microsoft Store app data keeps
its device state, so the ChatGPT agent goes on naming the new PC after the old one. `identity`
reports both; `--fix` removes the foreign enrollment, with a backup. See
[Moving to a new machine](docs/RISKS.md#moving-to-a-new-machine).

## Safety

- `scan` never writes to an agent's files. SQLite databases are copied (with `-wal`/`-shm`) to a
  temp dir and read there, so a running agent is never locked or disturbed. A test asserts that
  no file in a fake agent home changes during a scan.
- It never opens credential files and strips `user:token@` from every git URL before printing.
- Reports contain paths, counts and dates, not conversation text. They do contain your folder
  names: read one before you share it.
- `move --yes` and `undo` refuse while any agent runs, including npm-installed CLIs.
- With `--home <copy>`, environment variables such as `%APPDATA%` and `$CODEX_HOME` are
  ignored, so working on a copy never touches your real profile.
- Nothing is sent anywhere. `agentroot` makes no network calls.

The software is provided as is, without warranty (see [LICENSE](LICENSE)). It edits files that
belong to other vendors' apps; it is not affiliated with or endorsed by Anthropic, OpenAI or
Google.

## Docs

- [docs/STORAGE.md](docs/STORAGE.md): where each agent records a project path, with evidence.
- [docs/RISKS.md](docs/RISKS.md): what breaks when a folder moves, and the rules `move` follows.

## Contributing

Reports from other machines are the most useful contribution right now: other operating
systems, other app versions, other agents. Open an issue with the command, the output and your
versions. Pull requests are welcome; run `python -m pytest` first. To report a security
problem privately, see [SECURITY.md](SECURITY.md).

## Prior art

claude-repath, [claudepath](https://pypi.org/project/claudepath/) and
[claude-mover](https://github.com/automatix/claude-mover) move Claude Code projects;
[repo-sessions](https://github.com/firish/repo-sessions) syncs Claude and Codex sessions through
git; cass (coding_agent_session_search) searches sessions across agents.
`agentroot` exists because none of them covers Codex's and Antigravity's registries or groups the
three agents by project.

## License

MIT
