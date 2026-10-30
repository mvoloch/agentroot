# Risk map

What can go wrong when a tool moves a project folder that Claude Code, Codex and Antigravity
have sessions for, and the rule `agentroot` follows for each. Evidence is in
[STORAGE.md](STORAGE.md).

`scan` is read-only and already respects every rule that applies to reading. The rules marked
**apply** are the contract the move command must meet before it ships.

| # | Risk | Where | Rule | Status |
|---|---|---|---|---|
| 1 | **Rewriting conversation content corrupts the agent's own index.** Codex keeps byte offsets into each rollout (`thread_history_1.sqlite`); Antigravity stores protobuf, whose strings are length-prefixed. A search-and-replace that changes a path's length breaks both. | Codex, Antigravity | **Never rewrite conversation bodies.** Rewrite only registries, indexes and trust lists. Old conversations keep their historical cwd and resume from the new folder (`codex resume --cd`, Claude session folder rename). | apply |
| 2 | **Editing while the agent runs.** The apps hold state in memory and write it back, or hold SQLite WAL locks. Edits get overwritten or collide. | all | `apply` refuses to run while any agent process is alive (`claude`, `Claude`, `codex`, `Codex`, `agy`, `Antigravity`, `language_server_*`). Lock files are not proof of anything. | apply |
| 3 | **Shared stores counted or rewritten twice.** `~/.claude-corp/projects` was a junction to `~/.claude/projects`. | Claude | Resolve real paths; each physical file belongs to one home. | **scan done**, apply |
| 4 | **Two stores with one name.** `~/.codex/state_5.sqlite` (910 threads) and `~/.codex/sqlite/state_5.sqlite` (19) are different databases. | Codex | Address stores by full path, never by file name. | **scan done** |
| 5 | **Eight spellings of one path.** Lower-cased, forward-slash, `\\?\`, `file:///c%3A/`, encoded folder names. | all | Match on the normalized key; write back in the store's own spelling. | scan done (match), apply (write) |
| 6 | **Prefix false positives.** `C:\a\proj` must not rewrite `C:\a\project2`. Windows is case-insensitive. | all | Match whole path components, case-insensitively on Windows. | **done** (`paths.is_within`) |
| 7 | **Git worktrees break when their main clone moves**, and vice versa. | git | Move with `git worktree move`, then `git worktree repair`; verify every worktree with `git worktree list`. | apply |
| 8 | **Credentials leak.** Real remotes embed tokens (`https://user:TOKEN@host/repo.git`); agent homes hold OAuth files and cookies. | all | Strip userinfo from every URL before it is stored or printed. Never open `auth.json`, `.credentials.json`, `oauth_creds.json`, `google_accounts.json`, cookies, `Local State`. | **done** (tested) |
| 9 | **Git inside a cloud-synced folder** (OneDrive, Dropbox). Sync and git fight over the same files; conflict copies and corrupt repos follow. Syncing live agent databases corrupts them. | user setup | `scan` flags it. Recommended layout keeps code out of synced folders; never point a sync tool at an agent home while the agent runs. | **flagged** |
| 10 | **Gemini CLI reallocates the slug.** A moved folder gets `proj-1`; old history stays under `proj`. | Gemini CLI | Rewrite `projects.json` key and both `.project_root` files together, keep the slug. | apply |
| 11 | **VS Code-style workspace hash** changes with the folder URI. | Antigravity app/IDE | Leave `workspaceStorage` alone: only open tabs and panel state are lost; the agent regenerates it. | design |
| 12 | **Compressed rollouts** (`.jsonl.zst`, 776 of 853). | Codex | Read with Python 3.14 `compression.zstd`; on older Python, report them as unread instead of guessing. | **done** |
| 13 | **Format drift.** These are private formats that change between releases. | all | Adapters record the schema they understand (Codex `_sqlx_migrations` max version, table columns). `apply` refuses unknown versions; `scan` degrades to "unread". | apply |
| 14 | **Sessions already orphaned.** 236 sessions on the test machine point to deleted worktrees; 55 Codex threads point to missing rollouts. | all | Report, never "fix" by guessing. Not caused by agentroot. | **reported** |
| 15 | **Desktop session lists may cache.** Untested whether each app's sidebar reflects a rewritten index. | Claude desktop, Codex app, Antigravity app | After `apply`, `verify` opens nothing but checks every store; the user resumes one session per agent before deleting the backup. | apply |
| 16 | **Hidden locations.** Microsoft Store Codex keeps worktrees under `Packages\OpenAI.Codex_*\LocalCache`. `~/.gemini/antigravity-backup` mirrors the app home. | Codex, Antigravity | Discover them; treat the backup mirror as read-only. | **scan done** |
| 17 | **No undo.** A half-applied move is worse than none. | all | Back up every file before writing (with `-wal`/`-shm`), journal each change, `agentroot undo` replays the journal backwards. Write SQLite only through SQLite, with the app closed, then `PRAGMA quick_check`. | apply |
| 18 | **Temporary and scratch folders look like projects** (43 on the test machine). | all | Classified as temporary; never moved into the project root. | **done** |

## What `apply` will do, in order

1. `scan`, and refuse if any agent process runs or any store has an unknown schema.
2. Back up every store it will touch into `~/.agentroot/backups/<timestamp>/`, with a manifest of hashes.
3. Move the folder (`git worktree move` for worktrees), then `git worktree repair`.
4. Rewrite registries: Claude (`projects/` folder rename, `.claude.json` keys, desktop session JSON, `git-worktrees.json`), Codex (`threads.cwd`, `project_roots`, `config.toml`, global-state roots, `codex-dev.db` catalog), Antigravity/Gemini (`conversation_summaries.workspace_uris`, project configs, `projects.json` + `.project_root`, trust lists).
5. Leave a directory junction at the old path for 30 days, so anything missed still resolves.
6. `verify`: re-scan, assert no session points at the old path except conversation bodies, SQLite `quick_check`, JSON/TOML parse.
7. Journal everything; `agentroot undo <timestamp>` reverses it.
