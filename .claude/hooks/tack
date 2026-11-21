#!/usr/bin/env python3
"""tack runtime: stack detection, the verification contract, and Claude Code hooks.

This single file is stdlib-only (Python 3.11+). `tack init` vendors it into a project
as `.claude/hooks/tack`, so hooks, agents and CI work for every teammate
without installing anything. The `tack` CLI imports this same module.

Usage (vendored):
    python3 .claude/hooks/tack verify [--only lint,test] [--changed] [--json]
    python3 .claude/hooks/tack detect [--write]
    python3 .claude/hooks/tack hook <name>   (session-start, guard-bash,
                                                        protect-files, format, stop-verify)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUNTIME_VERSION = "0.1.0"
MANIFEST = "tack.toml"
PROGRESS_FILE = "PROGRESS.md"

#: Canonical check names, in the order they run. Every stack maps onto these.
CHECKS = ("setup", "format", "lint", "typecheck", "test", "build")
DEFAULT_VERIFY = ("format", "lint", "typecheck", "test")

OUTPUT_TAIL = 60  # lines of output kept per failing check

#: Decode subprocess output as UTF-8 everywhere (Windows defaults to a legacy code page).
TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}
VENDORED_PATH = ".claude/hooks/tack"

#: Default agent for `tack loop`: headless Claude Code that may edit files and run the
#: checks itself. JSON output lets tack record the result and (estimated) cost.
DEFAULT_AGENT = (
    "claude -p {prompt} --permission-mode acceptEdits --output-format json"
    ' --allowedTools "Bash(python3 .claude/hooks/tack verify:*)"'
)


# =========================================================================== manifest


@dataclass
class Component:
    name: str
    path: str  # relative to project root, "." for root
    stack: str
    commands: dict[str, str] = field(default_factory=dict)

    def abspath(self, root: Path) -> Path:
        return (root / self.path).resolve()


@dataclass
class Manifest:
    root: Path
    name: str
    status: str  # "new" until a stack is scaffolded, then "active"
    components: list[Component]
    hooks: dict
    guard: dict
    agent: dict

    def component_for(self, file: Path) -> Component | None:
        """Most specific component whose directory contains `file`."""
        file = file.resolve()
        best: tuple[int, Component] | None = None
        for comp in self.components:
            base = comp.abspath(self.root)
            if (file == base or base in file.parents) and (
                best is None or len(base.parts) > best[0]
            ):
                best = (len(base.parts), comp)
        return best[1] if best else None


def find_root(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for p in (cur, *cur.parents):
        if (p / MANIFEST).is_file():
            return p
    return None


def read_manifest_data(root: Path) -> dict:
    return tomllib.loads((root / MANIFEST).read_text(encoding="utf-8"))


def load_manifest(root: Path | None = None) -> Manifest:
    root = root or find_root()
    if root is None:
        raise FileNotFoundError(f"no {MANIFEST} found here or in any parent directory")
    data = read_manifest_data(root)
    comps = [
        Component(
            name=c.get("name") or root.name,
            path=c.get("path", "."),
            stack=c.get("stack", "generic"),
            commands={k: v for k, v in c.get("commands", {}).items() if v},
        )
        for c in data.get("components", [])
    ]
    project = data.get("project", {})
    return Manifest(
        root=root,
        name=project.get("name", root.name),
        status=project.get("status", "active"),
        components=comps,
        hooks=data.get("hooks", {}),
        guard=data.get("guard", {}),
        agent=data.get("agent", {}),
    )


# --------------------------------------------------------------------------- toml writer


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON strings are valid TOML basic strings
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value: {v!r}")


def _toml_table(prefix: str, table: dict, array: bool = False) -> list[str]:
    lines = [f"[[{prefix}]]" if array else f"[{prefix}]"]
    subtables = []
    for k, v in table.items():
        if isinstance(v, dict):
            subtables.append((k, v))
        else:
            lines.append(f"{k} = {_toml_value(v)}")
    for k, v in subtables:
        lines += _toml_table(f"{prefix}.{k}", v)
    return lines


def dump_toml(data: dict, header: str = "") -> str:
    """Minimal TOML writer for tack.toml's shape (tables, arrays of tables, scalars)."""
    out = [header.rstrip()] if header else []
    data = {k: v for k, v in data.items() if v != []}  # empty arrays of tables: omit
    scalars = {
        k: v
        for k, v in data.items()
        if not isinstance(v, dict | list)
        or (isinstance(v, list) and not any(isinstance(x, dict) for x in v))
    }
    out += [f"{k} = {_toml_value(v)}" for k, v in scalars.items()]
    for k, v in data.items():
        if k in scalars:
            continue
        out.append("")
        if isinstance(v, dict):
            out += _toml_table(k, v)
        else:
            for i, item in enumerate(v):
                if i:
                    out.append("")
                out += _toml_table(k, item, array=True)
    return "\n".join(out).strip() + "\n"


MANIFEST_HEADER = """\
# tack.toml: the project's verification contract.
# Every check (format, lint, typecheck, test...) maps to a real command per component.
# Hooks, agents and CI all run `python3 .claude/hooks/tack verify`.
# Docs: https://github.com/Mohidkz05/tack/blob/main/docs/manifest.md
"""


def default_manifest(name: str, status: str = "active") -> dict:
    return {
        "project": {"name": name, "status": status},
        "hooks": {"format_on_edit": True, "on_stop": ["lint", "typecheck"], "timeout": 300},
        "guard": {"protected": [], "deny_patterns": []},
        "agent": {"command": DEFAULT_AGENT, "max_iters": 5},
        "components": [],
    }


# =========================================================================== detection

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    "target",
    "vendor",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "out",
    "coverage",
    ".tack",
    ".claude",
    ".idea",
    ".vscode",
    ".gradle",
    "bin",
    "obj",
}
MAX_DEPTH = 4


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _python(d: Path) -> dict[str, str] | None:
    markers = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")
    if not any((d / m).is_file() for m in markers):
        return None
    text = " ".join(_read(d / m) for m in (*markers, "requirements-dev.txt")).lower()
    if (d / "uv.lock").is_file() or "[tool.uv" in text:
        run, setup = "uv run ", "uv sync"
    elif (d / "poetry.lock").is_file() or "[tool.poetry" in text:
        run, setup = "poetry run ", "poetry install"
    else:
        run = "python -m "
        setup = (
            "pip install -e ."
            if (d / "pyproject.toml").is_file() or (d / "setup.py").is_file()
            else "pip install -r requirements.txt"
        )
    cmds = {"setup": setup}
    if "black" in text and "ruff" not in text:
        cmds |= {
            "format": f"{run}black .",
            "format_check": f"{run}black --check .",
            "format_file": f"{run}black -q {{file}}",
        }
    else:
        cmds |= {
            "format": f"{run}ruff format .",
            "format_check": f"{run}ruff format --check .",
            "format_file": f"{run}ruff format -q {{file}}",
            "format_globs": "*.py,*.pyi",
        }
    cmds["lint"] = f"{run}ruff check ."
    if "pyright" in text:
        cmds["typecheck"] = f"{run}pyright"
    elif "mypy" in text:
        cmds["typecheck"] = f"{run}mypy ."
    if "pytest" in text or (d / "tests").is_dir() or (d / "conftest.py").is_file():
        cmds["test"] = f"{run}pytest -q"
    return cmds


def _node(d: Path) -> dict[str, str] | None:
    pkg_file = d / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        pkg = json.loads(_read(pkg_file) or "{}")
    except json.JSONDecodeError:
        pkg = {}
    scripts = pkg.get("scripts", {}) or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if (d / "pnpm-lock.yaml").is_file():
        pm, x, setup = "pnpm", "pnpm exec ", "pnpm install --frozen-lockfile"
    elif (d / "yarn.lock").is_file():
        pm, x, setup = "yarn", "yarn ", "yarn install"
    elif (d / "bun.lock").is_file() or (d / "bun.lockb").is_file():
        pm, x, setup = "bun", "bunx ", "bun install"
    else:
        pm, x = "npm", "npx "
        setup = "npm ci" if (d / "package-lock.json").is_file() else "npm install"

    def script(*names: str) -> str | None:
        for n in names:
            if n in scripts:
                return f"{pm} run {n}"
        return None

    cmds = {"setup": setup}
    if "@biomejs/biome" in deps:
        cmds |= {
            "format": f"{x}biome format --write .",
            "format_check": f"{x}biome format .",
            "format_file": f"{x}biome format --write {{file}}",
            "lint": script("lint") or f"{x}biome lint .",
        }
    else:
        if "prettier" in deps:
            cmds |= {
                "format": f"{x}prettier --write .",
                "format_check": f"{x}prettier --check .",
                "format_file": f"{x}prettier --write --log-level warn {{file}}",
            }
        lint = script("lint") or (f"{x}eslint ." if "eslint" in deps else None)
        if lint:
            cmds["lint"] = lint
    if s := script("format:check", "format-check"):
        cmds["format_check"] = s
    tc = script("typecheck", "type-check", "tsc")
    if tc or (d / "tsconfig.json").is_file():
        cmds["typecheck"] = tc or f"{x}tsc --noEmit"
    test = scripts.get("test", "")
    if test and "no test specified" not in test:
        cmds["test"] = f"{pm} run test"
    if b := script("build"):
        cmds["build"] = b
    return cmds


def _go(d: Path) -> dict[str, str] | None:
    if not (d / "go.mod").is_file():
        return None
    has_golangci = any(
        (d / f).is_file() for f in (".golangci.yml", ".golangci.yaml", ".golangci.toml")
    )
    return {
        "setup": "go mod download",
        "format": "gofmt -w .",
        "format_check": 'test -z "$(gofmt -l .)"',
        "format_file": "gofmt -w {file}",
        "lint": "golangci-lint run" if has_golangci else "go vet ./...",
        "test": "go test ./...",
        "build": "go build ./...",
    }


def _rust(d: Path) -> dict[str, str] | None:
    if not (d / "Cargo.toml").is_file():
        return None
    return {
        "setup": "cargo fetch",
        "format": "cargo fmt",
        "format_check": "cargo fmt --check",
        "format_file": "cargo fmt",
        "format_globs": "*.rs",
        "lint": "cargo clippy --all-targets -- -D warnings",
        "test": "cargo test",
        "build": "cargo build",
    }


def _java(d: Path) -> dict[str, str] | None:
    if (d / "pom.xml").is_file():
        mvn = "./mvnw" if (d / "mvnw").is_file() else "mvn"
        cmds = {
            "setup": f"{mvn} -q dependency:resolve",
            "test": f"{mvn} -q test",
            "build": f"{mvn} -q package -DskipTests",
        }
        if "spotless" in _read(d / "pom.xml"):
            cmds |= {
                "format": f"{mvn} -q spotless:apply",
                "format_check": f"{mvn} -q spotless:check",
            }
        return cmds
    gradle_file = next(
        (d / f for f in ("build.gradle.kts", "build.gradle") if (d / f).is_file()), None
    )
    if gradle_file:
        g = "./gradlew" if (d / "gradlew").is_file() else "gradle"
        cmds = {"lint": f"{g} check -x test", "test": f"{g} test", "build": f"{g} build -x test"}
        if "spotless" in _read(gradle_file):
            cmds |= {"format": f"{g} spotlessApply", "format_check": f"{g} spotlessCheck"}
        return cmds
    return None


def _make(d: Path) -> dict[str, str] | None:
    mk = next((d / f for f in ("Makefile", "makefile", "GNUmakefile") if (d / f).is_file()), None)
    if not mk:
        return None
    targets = set(re.findall(r"^([A-Za-z][\w-]*)\s*:(?!=)", _read(mk), re.M))
    aliases = {
        "setup": ("setup", "install", "deps"),
        "format": ("format", "fmt"),
        "format_check": ("format-check", "fmt-check", "check-format"),
        "lint": ("lint",),
        "typecheck": ("typecheck", "types"),
        "test": ("test", "tests"),
        "build": ("build",),
    }
    cmds = {}
    for check, names in aliases.items():
        hit = next((n for n in names if n in targets), None)
        if hit:
            cmds[check] = f"make {hit}"
    return cmds or None


#: (stack name, detector). First match wins per directory; order = priority.
STACKS = [("python", _python), ("node", _node), ("go", _go), ("rust", _rust), ("java", _java)]


def _is_workspace_root(d: Path, stack: str) -> bool:
    if stack == "rust":
        return "[workspace]" in _read(d / "Cargo.toml")
    if stack == "node":
        return '"workspaces"' in _read(d / "package.json") or (d / "pnpm-workspace.yaml").is_file()
    if stack == "python":
        return "[tool.uv.workspace]" in _read(d / "pyproject.toml")
    if stack == "go":
        return (d / "go.work").is_file()
    return False


def detect(root: Path) -> list[Component]:
    """Find every component (a directory with a known stack marker) up to MAX_DEPTH."""
    root = root.resolve()
    found: list[Component] = []
    workspaces: list[tuple[Path, str]] = []

    def visit(d: Path, depth: int) -> None:
        for stack, fn in STACKS:
            cmds = fn(d)
            if cmds is None:
                continue
            inside_ws = any(s == stack and (w == d or w in d.parents) for w, s in workspaces)
            if not inside_ws:
                rel = d.relative_to(root).as_posix() or "."
                name = root.name if rel == "." else rel.replace("/", "-")
                if make := _make(d):  # Makefile targets fill gaps the stack didn't cover
                    cmds = {**{k: v for k, v in make.items() if k not in cmds}, **cmds}
                found.append(Component(name, rel, stack, cmds))
                if _is_workspace_root(d, stack):
                    workspaces.append((d, stack))
        if depth >= MAX_DEPTH:
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if child.name not in IGNORED_DIRS and not child.name.startswith("."):
                visit(child, depth + 1)

    visit(root, 0)
    if not found and (make := _make(root)):
        found.append(Component(root.name, ".", "generic", make))
    return found


def merge_components(existing: list[dict], detected: list[Component]) -> list[dict]:
    """Add newly detected components; for known paths, only fill in missing commands.

    User edits always win: an existing command is never overwritten.
    """
    by_path = {c.get("path", "."): c for c in existing}
    merged = [dict(c) for c in existing]
    index = {c.get("path", "."): i for i, c in enumerate(merged)}
    for comp in detected:
        if comp.path in by_path:
            cur = merged[index[comp.path]]
            cur["commands"] = {**comp.commands, **cur.get("commands", {})}
        else:
            merged.append(
                {
                    "name": comp.name,
                    "path": comp.path,
                    "stack": comp.stack,
                    "commands": dict(comp.commands),
                }
            )
    return merged


def write_detected(root: Path) -> tuple[dict, list[Component]]:
    """Detect components and merge them into tack.toml, creating it if needed."""
    path = root / MANIFEST
    data = read_manifest_data(root) if path.is_file() else default_manifest(root.name)
    detected = detect(root)
    data["components"] = merge_components(data.get("components", []), detected)
    if data["components"] and data.get("project", {}).get("status") == "new":
        data["project"]["status"] = "active"
    path.write_text(dump_toml(data, MANIFEST_HEADER), encoding="utf-8")
    return data, detected


# =========================================================================== git


def changed_files(root: Path) -> list[Path]:
    """Tracked changes vs HEAD plus untracked files. Empty if not a git repo."""

    def git(*args: str) -> list[str] | None:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30, **TEXT)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.splitlines() if out.returncode == 0 else None

    names: set[str] = set()
    head = git("diff", "--name-only", "HEAD")
    names |= set(head if head is not None else git("diff", "--name-only") or [])
    names |= set(git("diff", "--name-only", "--cached") or [])
    names |= set(git("ls-files", "--others", "--exclude-standard") or [])
    return sorted(root / n for n in names if n)


# =========================================================================== verify


@dataclass
class CheckResult:
    component: str
    check: str
    command: str
    status: str  # pass | fail | skip | error
    exit_code: int | None
    seconds: float
    output: str = ""


def run_shell(cmd: str, cwd: Path, timeout: int) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            **TEXT,
            timeout=timeout,
            env={**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tail(text: str, n: int = OUTPUT_TAIL) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join([f"... ({len(lines) - n} lines omitted)", *lines[-n:]])


def verify_component(
    m: Manifest, comp: Component, checks: tuple[str, ...], timeout: int, fail_fast: bool
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        # verify never mutates files: the `format` check runs `format_check`.
        cmd = comp.commands.get("format_check" if check == "format" else check)
        if not cmd:
            results.append(CheckResult(comp.name, check, "", "skip", None, 0.0))
            continue
        start = time.monotonic()
        code, out = run_shell(cmd, comp.abspath(m.root), timeout)
        status = "pass" if code == 0 else ("error" if code is None else "fail")
        results.append(
            CheckResult(
                comp.name,
                check,
                cmd,
                status,
                code,
                round(time.monotonic() - start, 2),
                "" if status == "pass" else tail(out),
            )
        )
        if fail_fast and status != "pass":
            break
    return results


def select_components(
    m: Manifest, names: set[str] | None = None, changed_only: bool = False
) -> list[Component]:
    comps = [c for c in m.components if not names or c.name in names]
    if changed_only:
        touched = {id(c) for f in changed_files(m.root) if (c := m.component_for(f))}
        comps = [c for c in comps if id(c) in touched]
    return comps


def verify(
    m: Manifest,
    checks: tuple[str, ...] = DEFAULT_VERIFY,
    only_components: set[str] | None = None,
    changed_only: bool = False,
    timeout: int = 900,
    fail_fast: bool = False,
    jobs: int | None = None,
) -> list[CheckResult]:
    """Run checks per component. Components run in parallel; checks run in order."""
    comps = select_components(m, only_components, changed_only)
    if not comps:
        return []
    with ThreadPoolExecutor(max_workers=jobs or min(8, len(comps))) as pool:
        futures = [pool.submit(verify_component, m, c, checks, timeout, fail_fast) for c in comps]
        return [r for fut in futures for r in fut.result()]


def summarize(results: list[CheckResult]) -> str:
    label = {"pass": "PASS", "fail": "FAIL", "error": "ERR ", "skip": "skip"}
    lines = []
    for r in results:
        timing = f"{r.seconds:>6.1f}s" if r.status != "skip" else " " * 7
        lines.append(f"  {label[r.status]}  {timing}  {r.component}:{r.check}  {r.command}")
    for r in results:
        if r.status in ("fail", "error"):
            lines += ["", f"--- {r.component}:{r.check} ({r.command})", r.output]
    return "\n".join(lines)


def summarize_markdown(results: list[CheckResult]) -> str:
    """GitHub-flavored report, e.g. for $GITHUB_STEP_SUMMARY or a PR comment."""
    icon = {"pass": "✅", "fail": "❌", "error": "⏱️", "skip": "⚪"}
    ok = passed(results)
    lines = [
        f"### tack verify: {'passed' if ok else 'failed'}",
        "",
        "| | Component | Check | Command | Time |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        cmd = f"`{r.command}`" if r.command else "not configured"
        secs = f"{r.seconds:.1f}s" if r.status != "skip" else ""
        lines.append(f"| {icon[r.status]} | {r.component} | {r.check} | {cmd} | {secs} |")
    for r in results:
        if r.status in ("fail", "error"):
            lines += [
                "",
                f"<details><summary>{r.component}:{r.check} output</summary>",
                "",
                "```text",
                r.output,
                "```",
                "</details>",
            ]
    return "\n".join(lines)


def quote_path(path: str) -> str:
    """Quote a path for the platform's shell (sh on POSIX, cmd.exe on Windows)."""
    return subprocess.list2cmdline([path]) if os.name == "nt" else shlex.quote(path)


def passed(results: list[CheckResult]) -> bool:
    return all(r.status in ("pass", "skip") for r in results)


# =========================================================================== guards

#: (regex, decision, reason). "deny" hard-blocks; "ask" makes a human confirm.
BASH_RULES: list[tuple[str, str, str]] = [
    (
        r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]*\s+)*(/|~|\$HOME|\*|\.)/?(\s|$|;|&)",
        "deny",
        "recursive delete of root, home, the project, or a bare glob",
    ),
    (
        r"\bgit\s+push\b(?=.*(\s--force\b|\s-f\b|\s--force-with-lease\b))(?=.*\b(main|master)\b)",
        "deny",
        "force-push to a protected branch",
    ),
    (r"\bgit\s+push\b.*\s\+(main|master)\b", "deny", "force-push to a protected branch"),
    (
        r"(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
        "deny",
        "piping a remote script straight into a shell",
    ),
    (r"\bmkfs(\.\w+)?\b|\bdd\b[^;&|]*\bof=/dev/", "deny", "writing to a block device"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "deny", "fork bomb"),
    (r"\bchmod\s+(-R\s+)?0?777\b", "deny", "world-writable permissions"),
    (
        r"(>>?|\btee\b(\s+-a)?)\s*\S*\.env(\.(?!example\b|sample\b|template\b)\w+)?(\s|$)",
        "deny",
        "writing to a secrets file",
    ),
    (r"\bgit\s+reset\s+--hard\b", "ask", "discards uncommitted work"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "ask", "deletes untracked files"),
    (r"\bgit\s+(push|commit)\b.*\s--no-verify\b", "ask", "skips repository hooks"),
    (r"(^|[;&|]\s*)sudo\b", "ask", "runs with elevated privileges"),
    (
        r"\b(npm|pnpm|yarn)\s+publish\b|\bcargo\s+publish\b|\btwine\s+upload\b|\buv\s+publish\b",
        "ask",
        "publishes a package",
    ),
]

DEFAULT_PROTECTED = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa*",
    "id_ed25519*",
    ".git/*",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
]
PROTECTED_ALLOW = {".env.example", ".env.sample", ".env.template"}
LOCKFILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
}


def check_bash(command: str, extra_patterns: list[str] | None = None) -> tuple[str, str] | None:
    rules = BASH_RULES + [
        (p, "deny", f"matches project guard rule /{p}/") for p in extra_patterns or []
    ]
    ask: tuple[str, str] | None = None
    for pattern, decision, reason in rules:
        if re.search(pattern, command):
            if decision == "deny":
                return decision, reason
            ask = ask or (decision, reason)
    return ask


def check_path(path: str, root: Path, extra: list[str] | None = None) -> str | None:
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None  # outside the project: Claude Code's own permissions apply
    if p.name in PROTECTED_ALLOW:
        return None
    if p.name in LOCKFILES:
        return f"{rel} is a lockfile; change it through the package manager instead"
    for pat in DEFAULT_PROTECTED + list(extra or []):
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(p.name, pat):
            return f"{rel} is protected (matches '{pat}')"
    return None


# =========================================================================== hooks


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))


def _pretool(decision: str, reason: str) -> None:
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": f"tack guard: {reason}",
            }
        }
    )


def hook_session_start(m: Manifest, _event: dict) -> int:
    """Give the agent its bearings: components, definition of done, and saved progress."""
    out = [f"[tack] Project '{m.name}' uses the tack harness (runtime {RUNTIME_VERSION})."]
    if m.status == "new" or not m.components:
        out.append(
            "This is a NEW project with no stack yet. Use the `bootstrap` skill to turn "
            "SPEC.md into a working, verified skeleton before writing features."
        )
    else:
        out.append("Components and their checks:")
        for c in m.components:
            cmds = ", ".join(f"{k}=`{v}`" for k, v in c.commands.items() if k in CHECKS)
            out.append(f"- {c.name} ({c.stack}, ./{c.path}): {cmds or 'none configured'}")
    out.append(
        f"Definition of done: `{self_command(m.root)} verify --changed` "
        "passes. Conventions live in AGENTS.md."
    )
    progress = m.root / PROGRESS_FILE
    if progress.is_file():
        text = tail(_read(progress), 80)
        out += ["", f"--- {PROGRESS_FILE} (saved memory from earlier sessions) ---", text]
    print("\n".join(out))
    return 0


def hook_guard_bash(m: Manifest, event: dict) -> int:
    verdict = check_bash(
        (event.get("tool_input") or {}).get("command", ""), m.guard.get("deny_patterns")
    )
    if verdict:
        _pretool(*verdict)
    return 0


def hook_protect_files(m: Manifest, event: dict) -> int:
    ti = event.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if path and (reason := check_path(path, m.root, m.guard.get("protected"))):
        _pretool("deny", reason)
    return 0


def hook_format(m: Manifest, event: dict) -> int:
    """PostToolUse: format the file that was just written. Never blocks the agent."""
    if not m.hooks.get("format_on_edit", True):
        return 0
    path = (event.get("tool_input") or {}).get("file_path")
    if not path or not Path(path).is_file():
        return 0
    comp = m.component_for(Path(path))
    template = comp.commands.get("format_file") if comp else None
    if not comp or not template:
        return 0
    globs = comp.commands.get("format_globs")
    if globs and not any(fnmatch.fnmatch(Path(path).name, g.strip()) for g in globs.split(",")):
        return 0
    run_shell(
        template.replace("{file}", quote_path(str(Path(path).resolve()))),
        comp.abspath(m.root),
        timeout=60,
    )
    return 0


def hook_stop_verify(m: Manifest, event: dict) -> int:
    """Stop: if code changed, run fast checks; block the stop when they fail."""
    if event.get("stop_hook_active"):
        return 0  # we already sent the agent back once this turn; don't loop forever
    checks = tuple(m.hooks.get("on_stop", ["lint", "typecheck"]))
    if not checks:
        return 0
    results = verify(m, checks=checks, changed_only=True, timeout=int(m.hooks.get("timeout", 300)))
    if passed(results):
        return 0
    _emit(
        {
            "decision": "block",
            "reason": "tack: checks failed on the code you changed. Fix them before finishing.\n"
            + summarize([r for r in results if r.status != "skip"]),
        }
    )
    return 0


HOOKS = {
    "session-start": hook_session_start,
    "guard-bash": hook_guard_bash,
    "protect-files": hook_protect_files,
    "format": hook_format,
    "stop-verify": hook_stop_verify,
}


def self_command(root: Path) -> str:
    """How an agent should invoke this runtime: the vendored copy if the project has one,
    otherwise this file's own location (e.g. inside the Claude Code plugin)."""
    if (root / VENDORED_PATH).is_file():
        return f"python3 {VENDORED_PATH}"
    return f'python3 "{Path(__file__).resolve().as_posix()}"'


def run_hook(name: str, stdin: str, from_plugin: bool = False) -> int:
    try:
        event = json.loads(stdin) if stdin.strip() else {}
    except json.JSONDecodeError:
        event = {}
    start = Path(event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    root = find_root(start)
    if root is None:
        return 0  # not a tack project: every hook is a no-op
    if from_plugin and (root / VENDORED_PATH).is_file():
        return 0  # the project's own vendored hooks handle it; don't run twice
    try:
        m = load_manifest(root)
    except Exception as exc:  # a broken manifest must never wedge the agent
        print(f"tack: could not read {MANIFEST}: {exc}", file=sys.stderr)
        return 0
    return HOOKS[name](m, event)


# =========================================================================== cli


def parse_csv(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or "").split(",") if v.strip())


def add_verify_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--only", help=f"comma-separated checks ({', '.join(CHECKS)})")
    p.add_argument("--component", "-c", help="comma-separated component names")
    p.add_argument("--changed", action="store_true", help="only components with git changes")
    p.add_argument("--fail-fast", action="store_true", help="stop a component at its first failure")
    p.add_argument("--timeout", type=int, default=900, help="per-command timeout (seconds)")
    p.add_argument("--jobs", "-j", type=int, help="components to run in parallel (default <=8)")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    fmt.add_argument("--markdown", action="store_true", help="GitHub-flavored report")


def cmd_verify(args: argparse.Namespace) -> int:
    m = load_manifest()
    checks = parse_csv(args.only) or DEFAULT_VERIFY
    if unknown := set(checks) - set(CHECKS):
        print(f"unknown check(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    results = verify(
        m,
        checks,
        set(parse_csv(args.component)) or None,
        args.changed,
        args.timeout,
        args.fail_fast,
        args.jobs,
    )
    ok = passed(results)
    if args.json:
        print(json.dumps({"ok": ok, "results": [asdict(r) for r in results]}, indent=2))
    elif args.markdown:
        print(summarize_markdown(results) if results else "### tack verify: nothing to check")
    elif not results:
        print("tack verify: nothing to check")
    else:
        print(summarize(results))
        print(f"\ntack verify: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def cmd_detect(args: argparse.Namespace) -> int:
    root = find_root() or Path.cwd()
    if args.write:
        data, detected = write_detected(root)
        print(f"updated {MANIFEST}: {len(data['components'])} component(s)")
    else:
        detected = detect(root)
    if args.json:
        print(json.dumps([asdict(c) for c in detected], indent=2))
    else:
        for c in detected:
            print(f"- {c.name} ({c.stack}) at ./{c.path}")
            for k, v in c.commands.items():
                print(f"    {k:<13} {v}")
        if not detected:
            print("no known stack found (python, node, go, rust, java, Makefile)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tack_runtime", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_verify_args(sub.add_parser("verify", help="run the verification contract"))
    dp = sub.add_parser("detect", help="detect stacks; --write merges them into tack.toml")
    dp.add_argument("--write", action="store_true")
    dp.add_argument("--json", action="store_true")
    hp = sub.add_parser("hook", help="run a Claude Code hook (event JSON on stdin)")
    hp.add_argument("name", choices=sorted(HOOKS))
    hp.add_argument("--plugin", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("version")
    args = parser.parse_args(argv)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "detect":
        return cmd_detect(args)
    if args.cmd == "hook":
        return run_hook(args.name, sys.stdin.read(), from_plugin=args.plugin)
    print(RUNTIME_VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
