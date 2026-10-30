from __future__ import annotations

import argparse
import json
import os
import sys

from agentroot import __version__, catalog, move, paths, report


def _is_real_home(home: str) -> bool:
    return paths.key(home) == paths.key(os.path.expanduser("~"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentroot", description="One folder per project for Claude Code, Codex and Antigravity.")
    ap.add_argument("--version", action="version", version=f"agentroot {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    home_help = "user home whose agent data to use (default: yours)"

    sc = sub.add_parser("scan", help="catalog projects, folders and sessions of every agent (read-only)")
    sc.add_argument("--home", default=os.path.expanduser("~"), help=home_help)
    sc.add_argument("--json", metavar="FILE", help="write the full catalog as JSON")
    sc.add_argument("--html", metavar="FILE", help="write a browsable HTML report")
    sc.add_argument("--limit", type=int, default=0, help="show only the N most recently active projects")

    hm = sub.add_parser("homes", help="list the data directories of every agent found")
    hm.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    mv = sub.add_parser("move", help="move a project folder and update every agent (dry run unless --yes)")
    mv.add_argument("src")
    mv.add_argument("dst")
    mv.add_argument("--home", default=os.path.expanduser("~"), help=home_help)
    mv.add_argument("--yes", action="store_true", help="apply the plan (without it, only print it)")
    mv.add_argument("--no-move", action="store_true", help="the folder is already at dst (or stays put): only rewrite references")
    mv.add_argument("--no-junction", action="store_true", help="do not leave a junction at the old path")
    mv.add_argument("--ignore-running", action="store_true", help="apply even if an agent seems to be running (not recommended)")
    mv.add_argument("--json", metavar="FILE", help="write the plan as JSON")

    un = sub.add_parser("undo", help="reverse a move using its journal (latest by default)")
    un.add_argument("id", nargs="?")
    un.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    vf = sub.add_parser("verify", help="check that no agent registry still points at the old path")
    vf.add_argument("src")
    vf.add_argument("dst")
    vf.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    jl = sub.add_parser("journal", help="list past moves")
    jl.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.cmd == "homes":
        for adapter in catalog.ALL:
            for h in adapter.homes(args.home):
                print(f"{h.agent:<15} {h.path}" + (f"  ({h.note})" if h.note else ""))
        return 0

    if args.cmd == "scan":
        scan = catalog.build(args.home)
        print(report.to_text(scan, args.limit))
        for path, render in ((args.json, report.to_json), (args.html, report.to_html)):
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(render(scan))
                print(f"\nwrote {path}")
        return 1 if scan.errors else 0

    try:
        if args.cmd == "move":
            p = move.plan(args.home, args.src, args.dst, move_folder=not args.no_move)
            print(move.summary(p))
            if args.json:
                with open(args.json, "w", encoding="utf-8") as f:
                    f.write(move.to_json(p))
            if not args.yes:
                print("\nDry run. Nothing was changed. Add --yes to apply.")
                return 0
            if _is_real_home(args.home) and not args.ignore_running:
                running = move.running_agents()
                if running:
                    print(f"\nRefusing: close these first, they would overwrite the changes: {', '.join(running)}")
                    return 2
            jid = move.execute(args.home, p, junction=not args.no_junction)
            problems = move.verify(args.home, args.src, args.dst)
            if args.no_move:  # with --no-move the folder itself is the user's business
                problems = [x for x in problems if "does not exist" not in x]
            print(f"\nApplied. Journal {jid}  (undo: agentroot undo {jid})")
            print("Verify: " + ("ok, no registry points at the old path" if not problems else "; ".join(problems)))
            return 0 if not problems else 3

        if args.cmd == "undo":
            data = move.undo(args.home, args.id)
            print(f"Undone {data['id']}: {data['dst']} -> {data['src']}")
            return 0

        if args.cmd == "verify":
            problems = move.verify(args.home, args.src, args.dst)
            print("ok" if not problems else "\n".join(problems))
            return 0 if not problems else 3

        if args.cmd == "journal":
            root = move.journal_root(args.home)
            for jid in sorted(os.listdir(root)) if os.path.isdir(root) else []:
                with open(os.path.join(root, jid, "journal.json"), encoding="utf-8") as f:
                    d = json.load(f)
                print(f"{jid}  {d['state']:<10}  {d['src']}  ->  {d['dst']}")
            return 0
    except move.MoveError as e:
        print(f"agentroot: {e}", file=sys.stderr)
        return 2
    return 0
