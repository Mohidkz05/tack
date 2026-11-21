"""tack command line: new, init, update, add, verify, loop, runs, doctor, detect."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, doctor, install, loop, runtime

SYMBOLS = {
    "created": "+",
    "updated": "~",
    "merged": "~",
    "kept": "!",
    "unchanged": "=",
    "removed": "-",
}
LEVEL_SYMBOLS = {"ok": ("✓", "32"), "warn": ("!", "33"), "fail": ("✗", "31")}


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def _report(actions: list[install.Action], verbose: bool = False) -> None:
    colors = {
        "created": "32",
        "updated": "36",
        "merged": "36",
        "kept": "33",
        "unchanged": "2",
        "removed": "35",
    }
    for a in actions:
        if a.verb == "unchanged" and not verbose:
            continue
        line = f"  {SYMBOLS[a.verb]} {a.verb:<9} {a.path}"
        if a.note:
            line += f"  ({a.note})"
        print(_color(line, colors[a.verb]))
    hidden = sum(a.verb == "unchanged" for a in actions)
    if hidden and not verbose:
        print(_color(f"  = {hidden} file(s) already up to date", "2"))


def _components_summary(root: Path) -> None:
    m = runtime.load_manifest(root)
    if not m.components:
        print("  no stack yet (it gets set up by the `bootstrap` skill)")
    for c in m.components:
        checks = [
            k
            for k in runtime.CHECKS
            if k in c.commands or (k == "format" and "format_check" in c.commands)
        ]
        print(f"  - {c.name} ({c.stack}) ./{c.path}: {', '.join(checks) or 'no checks found'}")


def _addons(root: Path) -> tuple[str, ...]:
    return tuple(runtime.read_manifest_data(root).get("project", {}).get("addons", []))


def _require_root(path: str = ".") -> Path | None:
    root = runtime.find_root(Path(path))
    if root is None:
        print(
            "tack: no tack.toml found here. Run `tack init` or `tack new` first.", file=sys.stderr
        )
    return root


# --------------------------------------------------------------------------- setup commands


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"tack: {root} is not a directory", file=sys.stderr)
        return 2
    already = (root / runtime.MANIFEST).is_file()
    print(f"tack {'update' if already else 'init'}: {root}")
    if not args.dry_run:
        runtime.write_detected(root)
        print("\nComponents:")
        _components_summary(root)
    print("\nFiles:")
    addons = _addons(root) if already else ()
    files = install.plan(install.context_for(root), addons=addons)
    _report(install.install(root, files, force=args.force, dry_run=args.dry_run), args.verbose)
    print("\nNext:")
    print("  1. Check the commands in tack.toml")
    print("  2. Run `tack verify`, then `tack doctor` if anything looks off")
    print("  3. Optional: `tack add ci` (GitHub checks), `tack add claude-github` (@claude bot)")
    print("  4. Commit tack.toml, AGENTS.md, CLAUDE.md, .claude/ and .tack/lock.json")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    root = Path(args.name).resolve()
    if root.exists() and any(root.iterdir()) and not args.force:
        print(
            f"tack: {root} already exists and is not empty. Use `tack init` there instead.",
            file=sys.stderr,
        )
        return 2
    root.mkdir(parents=True, exist_ok=True)
    if shutil.which("git") and not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)
    manifest = runtime.default_manifest(root.name, status="new")
    (root / runtime.MANIFEST).write_text(
        runtime.dump_toml(manifest, runtime.MANIFEST_HEADER), encoding="utf-8"
    )
    files = install.plan(install.context_for(root), seeds=("SPEC.md", "PROGRESS.md"))
    print(f"tack new: {root}\n")
    _report(install.install(root, files), args.verbose)

    if args.start:
        agent = shutil.which("claude")
        if not agent:
            print(
                "\ntack: `claude` is not on PATH; install Claude Code or drop --start.",
                file=sys.stderr,
            )
            return 1
        if os.name == "nt":  # no real exec on Windows
            return subprocess.run([agent, "/bootstrap"], cwd=root, check=False).returncode
        os.chdir(root)
        os.execv(agent, [agent, "/bootstrap"])
    print("\nNext:")
    print(f"  cd {args.name}")
    print('  claude "/bootstrap"     # Claude interviews you, writes SPEC.md and sets up the stack')
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = _require_root(args.path)
    if root is None:
        return 2
    if args.detect and not args.dry_run:
        runtime.write_detected(root)
    m = runtime.load_manifest(root)
    files = install.plan(install.context_for(root, m.name), addons=_addons(root))
    print(f"tack update: {root}")
    _report(install.install(root, files, force=args.force, dry_run=args.dry_run), args.verbose)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    root = _require_root()
    if root is None:
        return 2
    available = install.available_addons()
    if args.list or not args.addons:
        print("Add-ons:")
        current = set(_addons(root))
        for name in available:
            print(f"  {'*' if name in current else ' '} {name}")
        return 0
    if unknown := [a for a in args.addons if a not in available]:
        print(
            f"tack: unknown add-on(s): {', '.join(unknown)} (available: {', '.join(available)})",
            file=sys.stderr,
        )
        return 2
    data = runtime.read_manifest_data(root)
    project = data.setdefault("project", {})
    addons = list(dict.fromkeys([*project.get("addons", []), *args.addons]))
    project["addons"] = addons
    (root / runtime.MANIFEST).write_text(
        runtime.dump_toml(data, runtime.MANIFEST_HEADER), encoding="utf-8"
    )
    files = install.plan(install.context_for(root), addons=tuple(addons))
    print(f"tack add: {', '.join(args.addons)}")
    _report(install.install(root, files, force=args.force), args.verbose)
    if "claude-github" in args.addons:
        print("\nNext: add an ANTHROPIC_API_KEY secret to the GitHub repo:")
        print("  gh secret set ANTHROPIC_API_KEY")
    return 0


# --------------------------------------------------------------------------- run commands


def cmd_loop(args: argparse.Namespace) -> int:
    root = _require_root()
    if root is None:
        return 2
    m = runtime.load_manifest(root)
    if m.status == "new" or not m.components:
        print(
            'tack: this project has no stack yet. Run claude "/bootstrap" first.', file=sys.stderr
        )
        return 2
    checks = runtime.parse_csv(args.only) or runtime.DEFAULT_VERIFY
    result = loop.run_loop(
        m,
        args.task,
        agent=args.agent,
        max_iters=args.max_iters,
        checks=checks,
        changed_only=not args.all,
        agent_timeout=args.timeout,
        echo=not args.json,
    )
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        cost = f", ~${result.cost_usd:.2f} est." if result.cost_usd is not None else ""
        verdict = {
            "passed": "PASSED",
            "failed": "FAILED (iteration limit reached)",
            "agent_error": "AGENT ERROR",
            "interrupted": "INTERRUPTED",
        }[result.status]
        print(
            f"\n[tack] loop {verdict}: {len(result.iterations)} iteration(s), "
            f"{result.seconds:.0f}s{cost}"
        )
        print(f"[tack] log: {result.log_path}")
    return 0 if result.status == "passed" else 1


def cmd_runs(args: argparse.Namespace) -> int:
    root = _require_root()
    if root is None:
        return 2
    runs = loop.list_runs(root, args.limit)
    if args.json:
        print(json.dumps(runs, indent=2))
        return 0
    if not runs:
        print('no runs yet: try `tack loop "<task>"`')
    for r in runs:
        cost = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "-"
        secs = f"{r['seconds']:.0f}s" if r["seconds"] is not None else "-"
        print(
            f"  {r['when'][:16]}  {r['status']:<11} {r['iterations'] or '-':>2} it  "
            f"{secs:>6}  {cost:>9}  {r['task'][:60]}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = _require_root()
    if root is None:
        return 2
    findings = doctor.check(root)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print(f"tack doctor: {root}\n")
        for f in findings:
            sym, color = LEVEL_SYMBOLS[f.level]
            print(_color(f"  {sym} {f.message}", color))
            if f.fix:
                print(f"      → {f.fix}")
        worst = (
            "fail"
            if any(f.level == "fail" for f in findings)
            else ("warn" if any(f.level == "warn" for f in findings) else "ok")
        )
        print(
            {
                "ok": "\nAll good.",
                "warn": "\nWorks, with warnings.",
                "fail": "\nBroken: fix the ✗ items.",
            }[worst]
        )
    return 1 if any(f.level == "fail" for f in findings) else 0


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tack",
        description="A stack-agnostic harness for AI-assisted development.",
    )
    p.add_argument("--version", action="version", version=f"tack {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sp = sub.add_parser("new", help="start a new project (Claude sets up the stack)")
    sp.add_argument("name", help="directory to create")
    sp.add_argument("--start", action="store_true", help="launch Claude Code into /bootstrap")
    sp.add_argument("--force", action="store_true", help="allow a non-empty directory")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("init", help="add tack to an existing project")
    sp.add_argument("path", nargs="?", default=".")
    sp.add_argument("--force", action="store_true", help="replace files you have edited")
    sp.add_argument("--dry-run", action="store_true", help="show what would change")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("update", help="refresh tack's files, keeping your edits")
    sp.add_argument("path", nargs="?", default=".")
    sp.add_argument("--detect", action="store_true", help="also re-detect components")
    sp.add_argument("--force", action="store_true", help="replace files you have edited")
    sp.add_argument("--dry-run", action="store_true", help="show what would change")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("add", help="add an add-on (ci, claude-github); no args lists them")
    sp.add_argument("addons", nargs="*")
    sp.add_argument("--list", action="store_true")
    sp.add_argument("--force", action="store_true", help="replace files you have edited")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("verify", help="run checks (format, lint, typecheck, test)")
    runtime.add_verify_args(sp)
    sp.set_defaults(func=runtime.cmd_verify)

    sp = sub.add_parser("loop", help="let an agent work on a task until the checks pass")
    sp.add_argument("task", help='what to do, e.g. "add a /health endpoint"')
    sp.add_argument("--agent", help="agent command; {prompt} is replaced (default: tack.toml)")
    sp.add_argument("--max-iters", "-n", type=int, help="attempt limit (default: tack.toml or 5)")
    sp.add_argument("--only", help="checks to require (default: format,lint,typecheck,test)")
    sp.add_argument("--all", action="store_true", help="verify every component, not just changed")
    sp.add_argument("--timeout", type=int, default=1800, help="per-attempt agent timeout (s)")
    sp.add_argument("--json", action="store_true", help="quiet; print the result as JSON")
    sp.set_defaults(func=cmd_loop)

    sp = sub.add_parser("runs", help="list recent `tack loop` runs")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_runs)

    sp = sub.add_parser("doctor", help="check the setup for problems")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("detect", help="show detected stacks; --write merges into tack.toml")
    sp.add_argument("--write", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=runtime.cmd_detect)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on ✓/✗ in a legacy console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"tack: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
