"""tack command line: new, init, update, verify, detect."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, install, runtime

SYMBOLS = {"created": "+", "updated": "~", "merged": "~", "kept": "!", "unchanged": "="}


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def _report(actions: list[install.Action], verbose: bool = False) -> None:
    colors = {"created": "32", "updated": "36", "merged": "36", "kept": "33", "unchanged": "2"}
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


# --------------------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"tack: {root} is not a directory", file=sys.stderr)
        return 2
    already = (root / runtime.MANIFEST).is_file()
    print(f"tack {'update' if already else 'init'}: {root}")
    runtime.write_detected(root)
    print("\nComponents:")
    _components_summary(root)
    print("\nFiles:")
    files = install.plan(install.context_for(root))
    _report(install.install(root, files, force=args.force, dry_run=args.dry_run), args.verbose)
    print("\nNext:")
    print("  1. Check the commands in tack.toml")
    print("  2. Run `tack verify` (or `python3 .claude/hooks/tack_runtime.py verify`)")
    print("  3. Commit tack.toml, AGENTS.md, CLAUDE.md, .claude/ and .tack/lock.json")
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
        os.chdir(root)
        os.execv(agent, [agent, "/bootstrap"])
    print("\nNext:")
    print(f"  cd {args.name}")
    print('  claude "/bootstrap"     # Claude interviews you, writes SPEC.md and sets up the stack')
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = runtime.find_root(Path(args.path))
    if root is None:
        print("tack: no tack.toml found. Run `tack init` first.", file=sys.stderr)
        return 2
    if args.detect:
        runtime.write_detected(root)
    m = runtime.load_manifest(root)
    seeds = ("PROGRESS.md",)
    files = install.plan(install.context_for(root, m.name), seeds=seeds)
    print(f"tack update: {root}")
    _report(install.install(root, files, force=args.force, dry_run=args.dry_run), args.verbose)
    return 0


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

    sp = sub.add_parser("verify", help="run checks (format, lint, typecheck, test)")
    runtime.add_verify_args(sp)
    sp.set_defaults(func=runtime.cmd_verify)

    sp = sub.add_parser("detect", help="show detected stacks; --write merges into tack.toml")
    sp.add_argument("--write", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=runtime.cmd_detect)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"tack: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
