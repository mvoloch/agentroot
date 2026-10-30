from __future__ import annotations

import dataclasses
import html
import json

from agentroot import __version__
from agentroot.catalog import NO_PROJECT, Scan, flags

AGENTS = ("claude-code", "claude-desktop", "codex", "antigravity")
SHORT = {"claude-code": "claude", "claude-desktop": "desktop", "codex": "codex", "antigravity": "agy"}


def to_json(scan: Scan) -> str:
    return json.dumps(
        {
            "agentroot": __version__,
            "homes": [dataclasses.asdict(h) for h in scan.homes],
            "projects": [
                {**dataclasses.asdict(p), "sessions": p.sessions, "last_activity": p.last_activity, "flags": flags(p)}
                for p in scan.projects
            ],
            "sessions": [dataclasses.asdict(s) for s in scan.sessions],
            "references": [dataclasses.asdict(r) for r in scan.references],
            "errors": scan.errors,
        },
        ensure_ascii=False,
        indent=1,
    )


def _counts(d: dict[str, int]) -> str:
    return " ".join(f"{SHORT[a]}:{d[a]}" for a in AGENTS if d.get(a))


def to_text(scan: Scan, limit: int = 0) -> str:
    lines = ["Homes:"]
    for h in scan.homes:
        n = sum(1 for s in scan.sessions if s.home == h.path)
        lines.append(f"  {h.agent:<15} {n:>5} sessions  {h.path}" + (f"  ({h.note})" if h.note else ""))
    projects = [p for p in scan.projects if p.key != NO_PROJECT]
    lines.append("")
    lines.append(f"{len(projects)} projects, {len(scan.sessions)} sessions, {len(scan.references)} path references")
    lines.append("")
    for p in projects[: limit or None]:
        total = sum(p.sessions.values())
        lines.append(f"{p.name}  [{len(p.locations)} folders, {total} sessions: {_counts(p.sessions)}]  last {p.last_activity[:10]}")
        if p.remote:
            lines.append(f"    remote  {p.remote}")
        for f in flags(p):
            lines.append(f"    ! {f}")
        for l in sorted(p.locations, key=lambda l: l.last_activity, reverse=True):
            tags = [l.kind] + (["temp"] if l.temporary else []) + (["cloud"] if l.cloud_synced else [])
            lines.append(f"    {','.join(tags):<20} {_counts(l.sessions):<28} {l.path}")
    outside = next((p for p in scan.projects if p.key == NO_PROJECT), None)
    if outside:
        lines.append("")
        lines.append(f"{NO_PROJECT}: {sum(outside.sessions.values())} sessions ({_counts(outside.sessions)}) in home/system folders")
    if scan.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  {e}" for e in scan.errors)
    return "\n".join(lines)


def to_html(scan: Scan) -> str:
    e = html.escape
    rows = []
    for p in scan.projects:
        locs = "".join(
            f"<tr class='loc'><td></td><td>{e(l.kind)}{' · temp' if l.temporary else ''}{' · cloud' if l.cloud_synced else ''}</td>"
            f"<td>{e(_counts(l.sessions))}</td><td>{e(l.last_activity[:10])}</td><td><code>{e(l.path)}</code></td></tr>"
            for l in sorted(p.locations, key=lambda l: l.last_activity, reverse=True)
        )
        fl = "".join(f"<span class='flag'>{e(f)}</span>" for f in flags(p))
        rows.append(
            f"<tr class='proj'><td><b>{e(p.name)}</b></td><td>{len(p.locations)} folders</td>"
            f"<td>{e(_counts(p.sessions))}</td><td>{e(p.last_activity[:10])}</td><td>{e(p.remote)} {fl}</td></tr>{locs}"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>agentroot scan</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mute:#666;--line:#e5e5e5;--warn:#9a3412;--warnbg:#fff1e6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--mute:#999;--line:#333;--warn:#fdba74;--warnbg:#3a2213}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:24px 16px}}
table{{border-collapse:collapse;width:100%}}td{{padding:4px 8px;border-top:1px solid var(--line);vertical-align:top}}
tr.loc td{{border-top:none;color:var(--mute);font-size:13px}}code{{font-size:12px;word-break:break-all}}
.flag{{display:inline-block;margin:0 4px 2px 0;padding:0 6px;border-radius:4px;background:var(--warnbg);color:var(--warn);font-size:12px}}
</style></head><body>
<h1>agentroot scan</h1>
<p>{len(scan.projects)} projects · {len(scan.sessions)} sessions · {len(scan.homes)} agent homes · agentroot {__version__}</p>
<table>{''.join(rows)}</table></body></html>"""
