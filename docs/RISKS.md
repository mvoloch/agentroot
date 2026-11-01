# Risk map

What can go wrong when a tool moves a project folder that Claude Code, Codex and Antigravity
have sessions for, and the rule `agentroot` follows for each. Evidence is in
[STORAGE.md](STORAGE.md).

`scan` is read-only. `move` and `undo` implement the rules below; the last column says how each
one is enforced. Every rule marked *test* has a regression test in `tests/test_move.py`,
`tests/test_safety.py` or `tests/test_identity.py`; most of the latter came from an adversarial audit that reproduced each
failure first.

Rehearsed on a copy of a real machine's data: 169,098 changes for one project across Claude
Code, the Claude app, Codex and Antigravity, integrity-checked (every SQLite database
`quick_check`, every JSON file and 215,839 JSONL lines parsed), then undone with zero byte
differences; and a second time with a session line appended after the move, where undo kept
that line.

| # | Risk | Where | Rule | Enforced |
|---|---|---|---|---|
| 1 | **Rewriting conversation content corrupts the agent's own index.** Codex keeps byte offsets into each rollout (`thread_history_1.sqlite`); Antigravity stores protobuf, whose strings are length-prefixed. A search-and-replace that changes a path's length breaks both. | Codex, Antigravity | **Never rewrite conversation bodies.** Rewrite only registries, indexes and trust lists. Old Codex rollouts keep their historical cwd; the junction left at the old path keeps it resolving. | design |
| 2 | **Editing while the agent runs.** The apps hold state in memory and write it back, or hold SQLite WAL locks. Edits get overwritten or collide. | all | `move --yes` and `undo` refuse while any agent process is alive: the apps and CLIs by name (`claude`, `Claude`, `codex`, `Codex`, `agy`, `Antigravity`, `gemini`, `language_server_*`) and npm installs by command line (`node … @anthropic-ai/claude-code`, `@openai/codex`, `@google/gemini-cli`). If processes cannot be listed, it refuses. Files are also re-hashed right before each write. Skipped only with `--ignore-running` or a `--home` that is not yours. | test |
| 3 | **Shared stores counted or rewritten twice.** `~/.claude-corp/projects` was a junction to `~/.claude/projects`. | Claude | Resolve real paths; each physical file belongs to one home. | test |
| 4 | **Two stores with one name.** `~/.codex/state_5.sqlite` (910 threads) and `~/.codex/sqlite/state_5.sqlite` (19) are different databases. | Codex | Address stores by full path, never by file name. | design |
| 5 | **Eight spellings of one path.** Lower-cased, forward-slash, `\\?\`, `file:///c%3A/`, encoded folder names. | all | Match on the normalized key; write back in the store's own spelling. | test |
| 6 | **Prefix false positives.** `C:\a\proj` must not rewrite `C:\a\project2`. Windows is case-insensitive. | all | Match whole path components, case-insensitively on Windows. | test |
| 7 | **Git worktrees break when their main clone moves**, and vice versa. | git | After the move, `git worktree repair` with every worktree's new path. | test (real git) |
| 8 | **Credentials leak.** Real remotes embed tokens (`https://user:TOKEN@host/repo.git`); agent homes hold OAuth files and cookies. | all | Strip userinfo from every URL before it is stored or printed. Never open `auth.json`, `.credentials.json`, `oauth_creds.json`, `google_accounts.json`, cookies, `Local State`. | test |
| 9 | **Git inside a cloud-synced folder** (OneDrive, Dropbox). Sync and git fight over the same files. | user setup | `scan` flags it. Keep code out of synced folders; never sync an agent home while the agent runs. | flagged |
| 10 | **Gemini CLI reallocates the slug.** A moved folder gets `proj-1`; old history stays under `proj`. | Gemini CLI | Rewrite `projects.json` key and both `.project_root` files together, keep the slug. | design |
| 11 | **VS Code-style workspace hash** changes with the folder URI. | Antigravity app/IDE | Leave `workspaceStorage` alone: only open tabs and panel state are lost; the app regenerates it. | design |
| 12 | **Compressed rollouts** (`.jsonl.zst`, 776 of 853). | Codex | Read with Python 3.14 `compression.zstd`. On older Python they are skipped: `scan` undercounts Codex sessions. They are never rewritten either way. | known gap |
| 13 | **Format drift.** These are private formats that change between releases. | all | No version check yet. What protects you instead: every rewritten file must parse and gain no duplicate key, every SQL update is guarded by the old value (`… where rowid = ? and col = old`), `quick_check` after each database, and any failure rolls back. An unknown format fails closed; it is not silently rewritten. | test |
| 14 | **Sessions already orphaned.** 236 sessions on the test machine point to deleted worktrees; 55 Codex threads point to missing rollouts. | all | Report, never "fix" by guessing. | reported |
| 15 | **Desktop session lists may cache.** Untested whether each app's sidebar reflects a rewritten index. | Claude desktop, Codex app, Antigravity app | After a move, resume one session per agent before relying on it. | **untested** |
| 16 | **Hidden locations.** Microsoft Store Codex keeps worktrees under `Packages\OpenAI.Codex_*\LocalCache`. `~/.gemini/antigravity-backup` mirrors the app home. | Codex, Antigravity | Discover them; treat the backup mirror as read-only. | design |
| 17 | **A half-applied move.** | all | Back up every file before writing (with `-wal`/`-shm`), journal each step *before* doing it, and on any failure reverse every step that can be reversed (never stopping at the first error) and report the rest. | test |
| 18 | **A copy that stops half way.** A rename that fails (a terminal or editor open inside the folder, git's read-only objects, another drive) used to fall back to copy-then-delete and could leave half a folder in each place. | all | Only `os.rename`, which is all or nothing. A destination on another drive is refused. | test |
| 19 | **Undo erasing new work.** Restoring the backups after the user kept working would erase new turns, new sessions, and other projects' entries in shared files. | all | Undo restores bytes only if every store is exactly as the move left it. Otherwise it moves the project back (a new, journaled move dst → src), which keeps everything written since. | test, rehearsal |
| 20 | **Undo blocked half way.** | all | The folder goes back first; if it cannot, nothing else is touched and the move stays applied, so `undo` can simply be run again. | test |
| 21 | **Relative paths.** `move proj ..\x` matched nothing yet would still move the folder. | all | Both paths are made absolute first. | test |
| 22 | **`--home` reaching the real profile.** `%APPDATA%`, `$CODEX_HOME` and `$CLAUDE_CONFIG_DIR` point at the real profile even when `--home` names a copy. | all | Environment variables are honoured only for the real home. | test, rehearsal |
| 23 | **Temporary and scratch folders look like projects** (43 on the test machine). | all | Classified as temporary; never moved into the project root. | test |
| 24 | **A profile copied to a new machine still names the old one.** Codex's `remote_control_enrollments` row (in `state_<N>.sqlite`) keeps the old machine's `server_name` and `server_id`, so both machines share one remote-control device. The Microsoft Store app's `Packages\OpenAI.Codex_*\LocalCache` also carries device state; the ChatGPT agent kept naming the new machine after the old one until that data was reset, even after a new installation id, a new enrollment, a new sign-in and a re-allowed computer. | Codex app, ChatGPT agent | `agentroot identity` reports both. An enrollment is flagged when its `server_name` differs from this machine's name. Store data is flagged when its state files were modified before they were created on this disk, which is what a copy leaves behind. Installed resources keep build dates and are ignored. `--fix` deletes the foreign enrollment with a backup, and the app enrolls again on its next start. The Store data needs `Reset-AppxPackage`, which agentroot only prints. | test, real machine |

## Moving to a new machine

`agentroot` moves projects within one machine. If you copy a whole profile to a new one:

- **Do not copy:**
  - `Packages\<agent app>_*\LocalCache` (Microsoft Store apps);
  - credentials: `auth.json`, `.credentials.json` and cookies.
- **Copy `~/.codex` if you want its history.** Then run `agentroot identity` on the new machine with every agent closed, and then `agentroot identity --fix`.
- **If you copied the Store data anyway:** reset that app, sign in, and re-allow any agent that works on this computer. An agent that can use only one computer at a time disconnects the other one when you allow this one.
- **Keep the old machine's app from enrolling as the new one.** Close it, or turn off its remote connections, before you decommission it.

## What `move` does, in order

1. Plan every change in memory. Refuse if:
   - the destination exists or is on another drive;
   - the source holds an agent home;
   - two Claude session folders would collide;
   - a rewritten file would not parse or would gain a duplicate key.
2. Refuse if any agent process runs.
3. Back up every store it will touch (with `-wal`/`-shm`) into `~/.agentroot/journal/<id>/files`.
4. Rename the folder (one atomic rename).
5. Rewrite registries:
   - **Claude:** session `cwd` fields, `.claude.json` keys, `history.jsonl`, desktop session JSON, `git-worktrees.json`.
   - **Codex:** `threads.cwd` in both state databases, `project_roots`, `config.toml`, global-state roots, `codex-dev.db` catalog and automations.
   - **Antigravity/Gemini:** `conversation_summaries.workspace_uris`, project configs, `projects.json` + `.project_root`, trust lists, `storage.json`, `state.vscdb`.

   Each file is re-hashed right before it is written. Each database runs in one transaction followed by `quick_check`.
6. Rename Claude's `projects/<encoded>` folders.
7. Run `git worktree repair`.
8. Leave a directory junction at the old path, so anything missed still resolves. It stays until you delete it.
9. Record the state of every store as the move left it, then `verify`: plan the same move again and require zero remaining references.

`agentroot undo [id]` reverses the last applied move (see risks 19 and 20).
