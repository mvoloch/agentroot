# Changelog

## 0.1.0 — 2026-11-01

First public release. Alpha, tested on Windows only (see "What was tested" in the README).

- `homes` and `scan`: read-only inventory of Claude Code, the Claude desktop app, Codex and
  Antigravity / Gemini CLI, grouped by git remote, with HTML and JSON reports.
- `move`, `verify`, `undo`, `journal`: relocate a project and rewrite every agent's registries,
  journaled, with backups and rollback.
- `tidy`: propose a one-folder-per-project layout for every git working tree on disk.
- `identity`: after copying a profile to a new machine, find what still names the old one.
