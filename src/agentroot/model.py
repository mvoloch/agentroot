from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Home:
    """One data directory of one agent. A machine can have several per agent."""
    agent: str        # "claude-code" | "claude-desktop" | "codex" | "antigravity"
    path: str
    note: str = ""    # e.g. "backup copy", "CLAUDE_CONFIG_DIR instance"


@dataclass(frozen=True)
class Session:
    agent: str
    home: str
    id: str
    path: str                 # working directory / workspace, as recorded (raw)
    updated: str = ""         # ISO-8601 when known
    remote_hint: str = ""     # remote URL the agent itself recorded (credentials stripped)
    store: str = ""           # file or table the path was read from
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reference:
    """A path an agent keeps outside sessions: trust lists, project registries, worktree maps."""
    agent: str
    home: str
    path: str
    store: str                # "file#field"
    role: str                 # "trust" | "project" | "worktree" | "recent"


@dataclass
class Location:
    path: str
    exists: bool
    kind: str                 # "clone" | "worktree" | "folder" | "missing"
    temporary: bool = False
    cloud_synced: bool = False
    sessions: dict[str, int] = field(default_factory=dict)   # agent -> count
    references: dict[str, int] = field(default_factory=dict)  # agent -> count
    last_activity: str = ""


@dataclass
class Project:
    key: str                  # remote key, or the folder key when there is no remote
    name: str
    remote: str = ""
    locations: list[Location] = field(default_factory=list)

    @property
    def sessions(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for loc in self.locations:
            for agent, n in loc.sessions.items():
                total[agent] = total.get(agent, 0) + n
        return total

    @property
    def last_activity(self) -> str:
        return max((l.last_activity for l in self.locations), default="")
