#!/usr/bin/env python3
"""Generate the Claude Code plugin in plugin/ from tack's templates.

The plugin carries the same skills, subagents, hooks and runtime that `tack init`
installs, so the two can never drift. Run after changing templates or the runtime:

    python3 scripts/build_plugin.py          # regenerate plugin/
    python3 scripts/build_plugin.py --check  # exit 1 if plugin/ is stale (used in CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tack import runtime  # noqa: E402

TEMPLATES = ROOT / "src/tack/templates/core/dot-claude"
PLUGIN_ONLY = ROOT / "src/tack/templates/plugin"  # extra files only the plugin ships
OUT = ROOT / "plugin"
LOCAL = "python3 .claude/hooks/tack"
PLUGIN = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/tack"'


def plugin_files() -> dict[str, str]:
    files: dict[str, str] = {}
    files[".claude-plugin/plugin.json"] = (
        json.dumps(
            {
                "name": "tack",
                "displayName": "tack",
                "version": runtime.RUNTIME_VERSION,
                "description": "Stack-agnostic harness: verify contract, guardrail hooks, and "
                "plan/build/review/debug/commit/ship skills for any project.",
                "author": {"name": "Mohidkz05", "url": "https://github.com/Mohidkz05"},
                "homepage": "https://github.com/Mohidkz05/tack",
                "repository": "https://github.com/Mohidkz05/tack",
                "license": "MIT",
                "keywords": [
                    "harness",
                    "verification",
                    "guardrails",
                    "tdd",
                    "code-review",
                    "agents-md",
                ],
            },
            indent=2,
        )
        + "\n"
    )

    for src in sorted((TEMPLATES / "skills").glob("*/SKILL.md")):
        files[f"skills/{src.parent.name}/SKILL.md"] = src.read_text(encoding="utf-8").replace(
            LOCAL, PLUGIN
        )
    for src in sorted(p for p in PLUGIN_ONLY.rglob("*") if p.is_file()):
        files[src.relative_to(PLUGIN_ONLY).as_posix()] = src.read_text(encoding="utf-8")
    for src in sorted((TEMPLATES / "agents").glob("*.md")):
        files[f"agents/{src.name}"] = src.read_text(encoding="utf-8").replace(LOCAL, PLUGIN)

    settings = json.loads((TEMPLATES / "settings.json").read_text(encoding="utf-8"))
    hooks = json.loads(json.dumps(settings["hooks"]))
    for groups in hooks.values():
        for group in groups:
            for h in group["hooks"]:
                name = h["command"].rsplit(" hook ", 1)[1]
                h["command"] = f"{PLUGIN} hook {name} --plugin"
    files["hooks/hooks.json"] = json.dumps({"hooks": hooks}, indent=2) + "\n"
    files["hooks/tack"] = Path(runtime.__file__).read_text(encoding="utf-8")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if plugin/ is out of date")
    args = parser.parse_args()
    wanted = plugin_files()
    existing = (
        {
            p.relative_to(OUT).as_posix(): p.read_text(encoding="utf-8")
            for p in OUT.rglob("*")
            if p.is_file()
        }
        if OUT.exists()
        else {}
    )
    if args.check:
        stale = sorted(
            k for k in wanted.keys() | existing.keys() if wanted.get(k) != existing.get(k)
        )
        if stale:
            print("plugin/ is out of date; run `python3 scripts/build_plugin.py`:")
            print("\n".join(f"  {s}" for s in stale))
            return 1
        print("plugin/ is up to date")
        return 0
    for rel in existing.keys() - wanted.keys():
        (OUT / rel).unlink()
    for rel, content in wanted.items():
        target = OUT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(f"wrote {len(wanted)} files to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
