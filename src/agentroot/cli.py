from __future__ import annotations

import argparse
import os
import sys

from agentroot import __version__, catalog, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentroot", description="Find every project your AI coding agents touched. Read-only.")
    ap.add_argument("--version", action="version", version=f"agentroot {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan", help="catalog projects, folders and sessions of every agent (read-only)")
    sc.add_argument("--home", default=os.path.expanduser("~"), help="user home to scan (default: yours)")
    sc.add_argument("--json", metavar="FILE", help="write the full catalog as JSON")
    sc.add_argument("--html", metavar="FILE", help="write a browsable HTML report")
    sc.add_argument("--limit", type=int, default=0, help="show only the N most recently active projects")

    hm = sub.add_parser("homes", help="list the data directories of every agent found")
    hm.add_argument("--home", default=os.path.expanduser("~"))

    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.cmd == "homes":
        for adapter in catalog.ALL:
            for h in adapter.homes(args.home):
                print(f"{h.agent:<15} {h.path}" + (f"  ({h.note})" if h.note else ""))
        return 0

    scan = catalog.build(args.home)
    print(report.to_text(scan, args.limit))
    for path, render in ((args.json, report.to_json), (args.html, report.to_html)):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(render(scan))
            print(f"\nwrote {path}")
    return 1 if scan.errors else 0
