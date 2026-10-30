# Where each agent records a project folder

What `agentroot scan` reads, and what `agentroot apply` will have to keep consistent.
Every row was checked on a real Windows 11 machine on 2026-10-30 (Claude Code 2.1.312,
Codex CLI 0.165.0, Antigravity `agy` 1.4.8) by reading field names, counts and paths, never
conversation text or credentials. Codex and Antigravity were also asked to describe their own
storage (read-only); where their answer and the files disagreed, the files win and the
disagreement is noted.

Confidence: **confirmed** = seen in the files · **agent-reported** = the agent said so, not yet
reproduced · **unknown** = nobody could establish it.

## Claude Code (CLI, IDE) and the Claude desktop app

| Store | Path field | Spelling | Notes |
|---|---|---|---|
| `~/.claude/projects/<encoded>/<session>.jsonl` | folder name, and `cwd` on each line | `C:\Users\me\proj`; folder = every non-alphanumeric char → `-` | **confirmed.** The folder name is *not* always the encoded cwd: the desktop app can file a session under another project's folder. Read `cwd`. |
| `~/.claude/projects/<encoded>/<session>/subagents/*.jsonl` | `cwd` | same | **confirmed**: 1,449 subagent transcripts vs 185 sessions on the test machine. |
| `~/.claude.json` → `projects` | object keys | `C:/Users/me/proj` and `C:\…` both occur | **confirmed** (146 keys). `~/.claude/.claude.json` can also exist. |
| `~/.claude/history.jsonl` | `project` | native | **confirmed.** Prompt history. |
| Extra config dirs `~/.claude-*` (`CLAUDE_CONFIG_DIR`) | same layout | — | **confirmed**: `~/.claude-corp/projects` was a *junction* to `~/.claude/projects`. Same files, two homes. |
| Desktop: `%APPDATA%\Claude\claude-code-sessions\**\*.json` (and `~/.claude-enterprise/` for Team) | `cwd`, `originCwd`, `worktreePath` | native | **confirmed** (156 + 44 files). |
| Desktop: `git-worktrees.json` | `worktrees.<name>.path`, `.baseRepo` | native | **confirmed.** |
| `<repo>/.claude/worktrees/<name>` | — | — | Worktrees Claude creates live **inside** the project. |

## OpenAI Codex (CLI, IDE extension, desktop app)

| Store | Path field | Spelling | Notes |
|---|---|---|---|
| `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]` | `session_meta.payload.cwd`, `runtime_workspace_roots[]`; `turn_context.payload.cwd`; `world_state…local.cwd` | native | **confirmed**: 77 plain, 776 zstd, 3 archived. |
| `~/.codex/state_5.sqlite` → `threads.cwd` | column | `\\?\C:\Users\me\proj` (all 910 rows) | **confirmed.** The app's conversation list. `threads.git_origin_url` too (394/910). |
| `state_5.sqlite` → `projects`, `project_roots(project_id, position, path)` | column | native | **confirmed**: 11 projects, 13 roots; a project can have several roots. |
| `~/.codex/sqlite/state_5.sqlite` | same schema | — | **confirmed**: a *different* store (19 threads) with the same file name. |
| `~/.codex/sqlite/codex-dev.db` | `local_thread_catalog.cwd`, `automations.cwds` | — | **confirmed** tables. |
| `~/.codex/thread_history_1.sqlite` | `thread_turns.rollout_byte_offset`, `rollout_end_byte_offset`; `thread_history_projection_state.next_rollout_byte_offset` | — | **confirmed.** Byte offsets into rollout files: **rewriting a rollout invalidates them.** |
| `~/.codex/.codex-global-state.json` | `local-projects.<id>.rootPaths[]`, `electron-saved-workspace-roots[]`, `active-workspace-roots[]`, `thread-workspace-root-hints`, `thread-writable-roots`, sidebar caches | native | **confirmed.** Also caches artifact file paths and MCP URIs (not project folders). |
| `~/.codex/config.toml` → `[projects.'<path>']` | table key | **lower-cased** native | **confirmed** (51). Trust level per folder. |
| `~/.codex/worktrees/<4 hex>/<repo>` | — | — | **confirmed.** Location not configurable as far as anyone found. The Microsoft Store build also keeps worktrees under `%LOCALAPPDATA%\Packages\OpenAI.Codex_*\LocalCache\Local\.codex\worktrees` (**agent-reported**). |
| Relocation knobs | `CODEX_HOME`, `sqlite_home` / `CODEX_SQLITE_HOME`, `log_dir` | — | **agent-reported.** |

Pre-existing on the test machine: 55 of 910 `threads.rollout_path` point to no file (neither
`.jsonl` nor `.jsonl.zst`). `agentroot` reports them; it does not cause or fix them.

## Google Antigravity (`agy` CLI, desktop app, IDE) and the Gemini CLI

Both live under `~/.gemini/`.

| Store | Path field | Spelling | Notes |
|---|---|---|---|
| `~/.gemini/<surface>/conversation_summaries.db` (`antigravity`, `antigravity-cli`) | `conversation_summaries.workspace_uris` (JSON list), `project_id` | `file:///c%3A/Users/me/proj` (app) or `file:///C:/Users/me/proj` (CLI) | **confirmed** (63 + 41 rows). |
| `~/.gemini/<surface>/conversations/<id>.db` | `steps.step_payload` (protobuf blobs) | — | **confirmed**: 41 `.db`. Antigravity itself described these as `.pb` files (7 exist): the format moved to SQLite. **Never rewrite**: protobuf strings are length-prefixed. |
| `~/.gemini/<surface>/brain/<id>/.system_generated/logs/transcript*.jsonl` | `workspaceUris`, tool `Path` args | URI / native | **agent-reported.** |
| `~/.gemini/config/projects/<uuid>.json` | `projectResources.resources[]`, `permissionGrants` | — | **confirmed** keys. Antigravity's own "project" entity. |
| `~/.gemini/config/config.json` | grants like `read_file(C:\proj)` | native | **agent-reported.** |
| `~/.gemini/antigravity-cli/settings.json` → `trustedWorkspaces[]` | list | native, case kept | **confirmed** (2 paths). |
| `~/.gemini/projects.json` (Gemini CLI) | `projects` keys → slug | **lower-case**, backslashes | **confirmed.** |
| `~/.gemini/history/<slug>/.project_root`, `tmp/<slug>/.project_root` | whole file | lower-case | **confirmed.** Moving a folder makes the Gemini CLI allocate `<slug>-1` and orphan the old history (**agent-reported**). |
| `~/.gemini/trustedFolders.json` | keys | **lower-case, forward slashes** `c:/users/me/proj` | **confirmed.** |
| `%APPDATA%\Antigravity\User\workspaceStorage\<hash>\workspace.json` | `folder` | `file:///c%3A/…` | **confirmed** (2). Hash derives from the URI: a moved folder gets a new hash (tabs/UI state only). |
| `%APPDATA%\Antigravity\User\globalStorage\storage.json`, `state.vscdb` (`ItemTable`) | JSON values | URI | **confirmed** paths present (3 + 16). |
| `~/.gemini/antigravity-backup/` | mirror of `antigravity/` | — | **confirmed** present; treated as a backup copy. |

## Spellings of one folder

One folder, `C:\Users\me\My Proj`, appears in these forms across the three ecosystems:

```
C:\Users\me\My Proj                 Claude cwd, Codex rollouts, project_roots, agy trustedWorkspaces
C:/Users/me/My Proj                 ~/.claude.json keys (some)
\\?\C:\Users\me\My Proj             Codex threads.cwd
c:\users\me\my proj                 Codex config.toml, Gemini projects.json, .project_root
c:/users/me/my proj                 Gemini trustedFolders.json
file:///c%3A/Users/me/My%20Proj     Antigravity app, VS Code-style storage
file:///C:/Users/me/My%20Proj       agy CLI workspace URIs
C--Users-me-My-Proj                 Claude Code session folder name
```

`agentroot.paths.key()` maps all of them to one comparison key; a rewrite must write each store
back in **its own** spelling.
