from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Iterator
from typing import Any


def iso(value: Any) -> str:
    """Seconds, milliseconds or an ISO string -> ISO-8601 UTC string ("" when unknown)."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        if n > 1e11:  # milliseconds
            n /= 1000
        return dt.datetime.fromtimestamp(n, dt.timezone.utc).isoformat(timespec="seconds")
    return str(value)


def mtime_iso(path: str) -> str:
    try:
        return iso(os.path.getmtime(path))
    except OSError:
        return ""


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def strings(obj: Any) -> Iterator[tuple[str, str]]:
    """(dotted.key, value) for every string inside a JSON value."""
    stack: list[tuple[str, Any]] = [("", obj)]
    while stack:
        prefix, cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend((f"{prefix}.{k}" if prefix else str(k), v) for k, v in cur.items())
        elif isinstance(cur, list):
            stack.extend((f"{prefix}[]", v) for v in cur)
        elif isinstance(cur, str):
            yield prefix, cur


def looks_like_path(s: str) -> bool:
    s = s.strip()
    return (
        s.lower().startswith("file:")
        or (len(s) > 2 and s[1] == ":" and s[2] in "\\/")
        or s.startswith("\\\\")
        or (s.startswith("/") and "/" in s[1:] and "\n" not in s)
    )
