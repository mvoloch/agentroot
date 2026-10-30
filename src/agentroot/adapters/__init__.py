"""One adapter per agent. Every adapter is read-only.

An adapter exposes:
    homes(user_home)      -> list[Home]       every data directory of that agent on this machine
    sessions(home)        -> Iterable[Session]
    references(home)      -> Iterable[Reference]
"""
from agentroot.adapters import antigravity, claude, codex

ALL = (claude, codex, antigravity)
