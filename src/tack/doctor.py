"""`tack doctor`: find what's missing, broken, or out of date in a tack project."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import install, runtime

OK, WARN, FAIL = "ok", "warn", "fail"
SHELL_BUILTINS = {"test", "[", "cd", "echo", "true", "false", "set", "export", "exit"}


@dataclass(frozen=True)
class Finding:
    level: str  # ok | warn | fail
    message: str
    fix: str = ""


def executable_of(command: str) -> str | None:
    """First real program a shell command runs (skips VAR=x prefixes and builtins)."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    for tok in tokens:
        if "=" in tok and not tok.startswith(("-", "/", ".")):
            continue  # env assignment
        return None if tok in SHELL_BUILTINS else tok
    return None


def _tool_available(tool: str, cwd: Path) -> bool:
    if tool.startswith("./") or tool.startswith("../"):
        return (cwd / tool).exists()
    return shutil.which(tool) is not None


def check(root: Path) -> list[Finding]:
    out: list[Finding] = []
    add = out.append

    # Hooks run `python3`, which may not be the interpreter running tack itself.
    # On Windows `python3` may be a Store stub that prints nothing, so probe each candidate.
    version = None
    for name in ("python3", "python"):
        py = shutil.which(name)
        if not py:
            continue
        try:
            probe = subprocess.run(
                [py, "-c", "import sys; print(*sys.version_info[:2])"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        parts = probe.stdout.split()
        if len(parts) == 2:
            version = (int(parts[0]), int(parts[1]))
            break
    if version and version >= (3, 11):
        add(Finding(OK, f"python3 is {version[0]}.{version[1]} (hooks need 3.11+)"))
    else:
        found = f"{version[0]}.{version[1]}" if version else "not found"
        add(
            Finding(
                FAIL,
                f"hooks need python3 >= 3.11 on PATH (found: {found})",
                "install Python 3.11+ and make it available as `python3`",
            )
        )

    try:
        m = runtime.load_manifest(root)
    except Exception as exc:
        add(Finding(FAIL, f"tack.toml could not be read: {exc}", "fix the TOML syntax"))
        return out
    add(Finding(OK, f"tack.toml ({len(m.components)} component(s))"))

    if m.status == "new":
        add(Finding(WARN, "project has no stack yet", 'run claude "/bootstrap"'))

    missing_tools: dict[str, list[str]] = {}
    for c in m.components:
        base = c.abspath(root)
        if not base.is_dir():
            add(
                Finding(
                    FAIL,
                    f"component '{c.name}' points to missing path ./{c.path}",
                    "fix the path in tack.toml or run `tack update --detect`",
                )
            )
            continue
        configured = [k for k in runtime.CHECKS if k in c.commands]
        if "format_check" in c.commands and "format" not in configured:
            configured.append("format")
        if not ({"lint", "test"} & set(configured)):
            add(
                Finding(
                    WARN,
                    f"component '{c.name}' has no lint or test command",
                    "add them under [components.commands] in tack.toml",
                )
            )
        for key, cmd in c.commands.items():
            if key == "format_globs":
                continue
            tool = executable_of(cmd)
            if tool and not _tool_available(tool, base):
                missing_tools.setdefault(tool, []).append(f"{c.name}:{key}")
    for tool, uses in sorted(missing_tools.items()):
        add(
            Finding(
                WARN,
                f"'{tool}' not found on PATH (used by {', '.join(uses[:3])}"
                f"{'...' if len(uses) > 3 else ''})",
                f"install {tool}",
            )
        )
    if m.components and not missing_tools:
        add(Finding(OK, "all check tools found on PATH"))

    vendored = root / ".claude/hooks/tack"
    if not vendored.is_file():
        add(
            Finding(
                FAIL,
                "vendored runtime missing (.claude/hooks/tack)",
                "run `tack update`",
            )
        )
    elif vendored.read_text(encoding="utf-8") != Path(runtime.__file__).read_text(encoding="utf-8"):
        add(Finding(WARN, "vendored runtime differs from this tack version", "run `tack update`"))
    else:
        add(Finding(OK, f"vendored runtime is current ({runtime.RUNTIME_VERSION})"))

    settings = root / ".claude/settings.json"
    try:
        hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
        wired = {
            e
            for e, groups in hooks.items()
            if any(
                install.TACK_MARK in h.get("command", "")
                for g in groups
                for h in g.get("hooks", [])
            )
        }
        need = {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
        if need <= wired:
            add(Finding(OK, "Claude Code hooks wired"))
        else:
            add(
                Finding(
                    WARN,
                    f"hooks missing for: {', '.join(sorted(need - wired))}",
                    "run `tack update`",
                )
            )
    except (OSError, json.JSONDecodeError):
        add(Finding(WARN, ".claude/settings.json missing or invalid", "run `tack update`"))

    agents = root / "AGENTS.md"
    if not agents.is_file() or "<!-- tack:begin" not in agents.read_text(encoding="utf-8"):
        add(Finding(WARN, "AGENTS.md has no tack block", "run `tack update`"))
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file() and "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
        add(
            Finding(
                WARN,
                "CLAUDE.md doesn't import @AGENTS.md",
                "add a line `@AGENTS.md` so Claude reads the shared rules",
            )
        )

    lock = install.read_lock(root).get("files", {})
    edited = [
        p
        for p, digest in lock.items()
        if (root / p).is_file() and install._sha((root / p).read_text(encoding="utf-8")) != digest
    ]
    if edited:
        add(Finding(OK, f"{len(edited)} managed file(s) customized by you (kept on update)"))

    if not (root / ".git").exists():
        add(Finding(WARN, "not a git repository", "run `git init`: --changed and hooks need git"))

    agent_tool = executable_of(m.agent.get("command", "claude"))
    if agent_tool and not shutil.which(agent_tool):
        add(
            Finding(
                WARN,
                f"agent '{agent_tool}' not on PATH (needed for `tack loop`)",
                "install it or set [agent].command in tack.toml",
            )
        )
    return out
