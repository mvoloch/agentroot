from __future__ import annotations

import argparse
import json
import os
import sys

from agentroot import __version__, catalog, identity, move, paths, report, tidy


def _is_real_home(home: str) -> bool:
    return paths.key(home) == paths.key(os.path.expanduser("~"))


def _refuse_running(args) -> bool:
    if not _is_real_home(args.home) or args.ignore_running:
        return False
    running = move.running_agents()
    if running:
        print(f"\nRefusing: close these first, they would overwrite the changes: {', '.join(running)}")
    return bool(running)


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
    un.add_argument("--ignore-running", action="store_true", help="undo even if an agent seems to be running (not recommended)")

    vf = sub.add_parser("verify", help="check that no agent registry still points at the old path")
    vf.add_argument("src")
    vf.add_argument("dst")
    vf.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    td = sub.add_parser("tidy", help="propose where every copy of every project should go (read-only)")
    td.add_argument("--home", default=os.path.expanduser("~"), help=home_help)
    td.add_argument("--root", default=os.path.join(os.path.expanduser("~"), "Projects"), help="where projects live (default ~/Projects)")
    td.add_argument("--json", metavar="FILE", help="write the proposal as JSON (review it before applying)")
    td.add_argument("--apply", action="store_true", help="list the MAIN, GATHER and ARCHIVE moves (with --yes, do them)")
    td.add_argument("--yes", action="store_true", help="with --apply: move the folders")
    td.add_argument("--ignore-running", action="store_true", help="apply even if an agent seems to be running (not recommended)")

    jl = sub.add_parser("journal", help="list past moves")
    jl.add_argument("--home", default=os.path.expanduser("~"), help=home_help)

    idn = sub.add_parser("identity", help="after copying a profile to a new machine: find agent identity that still names the old one")
    idn.add_argument("--home", default=os.path.expanduser("~"), help=home_help)
    idn.add_argument("--fix", action="store_true", help="remove remote-control enrollments of another machine (with a backup)")
    idn.add_argument("--ignore-running", action="store_true", help="fix even if an agent seems to be running (not recommended)")

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

    if args.cmd == "identity":
        found = identity.check(args.home)
        for f in found:
            print(f"{f.kind:<11} {f.path}\n            {f.detail}\n            fix: {f.fix}")
        if not found:
            print(f"ok: nothing names a machine other than {identity.hostname()}")
            return 0
        if not args.fix:
            return 3
        if _refuse_running(args):
            return 2
        for line in identity.fix(args.home):
            print(line)
        # store data needs an app reset, which agentroot does not do
        return 3 if any(f.kind == "store-data" for f in identity.check(args.home)) else 0

    if args.cmd == "tidy":
        trees = tidy.survey(args.home, progress=lambda t: print(".", end="", file=sys.stderr, flush=True))
        tidy.propose(trees, args.home, os.path.abspath(args.root))
        print(file=sys.stderr)
        print(tidy.summary(trees))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(tidy.to_dicts(trees), f, ensure_ascii=False, indent=1)
            print(f"\nwrote {args.json}")
        if not args.apply:
            return 0
        todo = tidy.moves(trees)
        print(f"\n{len(todo)} moves:")
        for t in todo:
            print(f"  {t.action:<8} {t.path} -> {t.dst}")
        if not args.yes:
            print("\nDry run. Nothing was changed. Add --yes to apply.")
            return 0
        if _refuse_running(args):
            return 2
        try:
            done = tidy.apply(trees, args.home)
        except move.MoveError as e:
            print(f"agentroot: {e}\nThe moves before it stay applied; `agentroot journal` lists them.", file=sys.stderr)
            return 1
        print(f"\nApplied {len(done)} moves.")
        return 0

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
            if _refuse_running(args):
                return 2
            jid = move.execute(args.home, p, junction=not args.no_junction)
            # with --no-move the folder itself is the user's business
            problems = move.verify(args.home, p.src, p.dst, check_folder=not args.no_move)
            print(f"\nApplied. Journal {jid}  (undo: agentroot undo {jid})")
            print("Verify: " + ("ok, no registry points at the old path" if not problems else "; ".join(problems)))
            return 0 if not problems else 3

        if args.cmd == "undo":
            if _refuse_running(args):
                return 2
            data = move.undo(args.home, args.id)
            print(f"{data['state']} {data['id']}: {data['dst']} -> {data['src']}")
            if data["state"].startswith("reversed by"):
                print("Some stores changed after the move, so the old bytes were not restored (that would erase\n"
                      "what was written since). The folder was moved back and every reference rewritten instead.")
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
