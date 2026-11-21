"""Write tack's files into a project without ever clobbering a user's own edits.

Every file has a *kind* that decides how it is written:

- managed: tack owns it. Updated only while it still matches what tack last wrote
           (tracked by hash in .tack/lock.json); if the user edited it, it is kept.
- block:   tack owns only the text between `<!-- tack:begin -->` and `<!-- tack:end -->`.
- merge:   JSON settings; tack adds its entries and never removes the user's.
- seed:    written once if missing, then belongs to the user forever.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import runtime

TEMPLATES = Path(__file__).parent / "templates"
LOCK_PATH = Path(".tack") / "lock.json"
BLOCK_RE = re.compile(r"<!-- tack:begin.*?-->.*?<!-- tack:end -->", re.S)

#: Settings entries containing this string belong to tack (pruned when tack drops them).
TACK_MARK = ".claude/hooks/tack"

BLOCK_FILES = {"AGENTS.md"}
MERGE_FILES = {".claude/settings.json"}


@dataclass(frozen=True)
class Planned:
    path: str  # relative to project root, posix
    content: str
    kind: str  # managed | block | merge | seed


@dataclass(frozen=True)
class Action:
    verb: str  # created | updated | merged | kept | unchanged | removed
    path: str
    note: str = ""


# --------------------------------------------------------------------------- planning


def _dest(rel: Path) -> str:
    """templates/core/dot-claude/x.md.tmpl -> .claude/x.md"""
    parts = ["." + p[4:] if p.startswith("dot-") else p for p in rel.parts]
    out = "/".join(parts)
    return out[: -len(".tmpl")] if out.endswith(".tmpl") else out


def render(text: str, context: dict[str, str]) -> str:
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def available_addons() -> list[str]:
    return sorted(p.name for p in (TEMPLATES / "addons").iterdir() if p.is_dir())


def _plan_dir(base: Path, context: dict[str, str]) -> list[Planned]:
    files = []
    for src in sorted(p for p in base.rglob("*") if p.is_file()):
        dest = _dest(src.relative_to(base))
        kind = "block" if dest in BLOCK_FILES else "merge" if dest in MERGE_FILES else "managed"
        files.append(Planned(dest, render(src.read_text(encoding="utf-8"), context), kind))
    return files


def plan(
    context: dict[str, str],
    seeds: tuple[str, ...] = ("PROGRESS.md",),
    addons: tuple[str, ...] = (),
) -> list[Planned]:
    files = _plan_dir(TEMPLATES / "core", context)
    runtime_src = Path(runtime.__file__).read_text(encoding="utf-8")
    files.append(Planned(".claude/hooks/tack", runtime_src, "managed"))
    for addon in addons:
        base = TEMPLATES / "addons" / addon
        if not base.is_dir():
            raise ValueError(
                f"unknown add-on '{addon}' (available: {', '.join(available_addons())})"
            )
        files += _plan_dir(base, context)
    seed_dir = TEMPLATES / "seed"
    for src in sorted(seed_dir.glob("*.tmpl")):
        dest = _dest(src.relative_to(seed_dir))
        if dest in seeds:
            files.append(Planned(dest, render(src.read_text(encoding="utf-8"), context), "seed"))
    return files


# GitHub Actions toolchain setup per stack. Indented to sit under `steps:`.
_STEP = "      "
CI_SETUP = {
    "uv": f"{_STEP}- uses: astral-sh/setup-uv@v7",
    "node": f'{_STEP}- uses: actions/setup-node@v7\n{_STEP}  with:\n{_STEP}    node-version: "22"',
    "pnpm": f"{_STEP}- uses: pnpm/action-setup@v6\n{_STEP}  with:\n{_STEP}    version: latest",
    "bun": f"{_STEP}- uses: oven-sh/setup-bun@v2",
    "go": f"{_STEP}- uses: actions/setup-go@v7\n{_STEP}  with:\n{_STEP}    go-version: stable",
    "rust": f"{_STEP}- uses: dtolnay/rust-toolchain@stable\n{_STEP}  with:\n"
    f"{_STEP}    components: rustfmt, clippy",
    "java": f"{_STEP}- uses: actions/setup-java@v6\n{_STEP}  with:\n"
    f'{_STEP}    distribution: temurin\n{_STEP}    java-version: "21"',
}


def ci_setup_steps(components: list[runtime.Component]) -> str:
    """Toolchain setup steps for exactly the stacks this project uses."""
    needed: list[str] = []
    for c in components:
        cmds = " ".join(c.commands.values())
        keys = {
            "python": ["uv"] if "uv " in cmds else [],
            "node": (["pnpm"] if "pnpm" in cmds else ["bun"] if "bun" in cmds else []) + ["node"],
            "go": ["go"],
            "rust": ["rust"],
            "java": ["java"],
        }.get(c.stack, [])
        needed += [k for k in keys if k not in needed]
    return "\n".join(CI_SETUP[k] for k in needed)


def context_for(root: Path, name: str | None = None) -> dict[str, str]:
    ctx = {"name": name or root.resolve().name, "date": _dt.date.today().isoformat()}
    try:
        ctx["setup_steps"] = ci_setup_steps(runtime.load_manifest(root).components)
    except (FileNotFoundError, OSError, ValueError):
        ctx["setup_steps"] = ""
    return ctx


# --------------------------------------------------------------------------- lock


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lock(root: Path) -> dict:
    try:
        return json.loads((root / LOCK_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": None, "files": {}}


def write_lock(root: Path, lock: dict) -> None:
    (root / LOCK_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / LOCK_PATH).write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- merging


def merge_block(existing: str, template: str) -> str:
    block = BLOCK_RE.search(template)
    if not block:
        return existing
    if BLOCK_RE.search(existing):
        return BLOCK_RE.sub(lambda _m: block.group(0), existing, count=1)
    return existing.rstrip() + "\n\n" + block.group(0) + "\n"


def _hook_commands(groups: list[dict]) -> set[str]:
    return {h.get("command", "") for g in groups for h in g.get("hooks", [])}


def _prune_tack_entries(settings: dict, template: dict) -> None:
    """Drop tack-owned permissions and hooks that the current template no longer has."""
    keep_perms = {i for items in template.get("permissions", {}).values() for i in items}
    for items in settings.get("permissions", {}).values():
        items[:] = [i for i in items if TACK_MARK not in i or i in keep_perms]
    keep_cmds = _hook_commands([g for gs in template.get("hooks", {}).values() for g in gs])
    for event, groups in list(settings.get("hooks", {}).items()):
        for g in groups:
            g["hooks"] = [
                h
                for h in g.get("hooks", [])
                if TACK_MARK not in h.get("command", "") or h["command"] in keep_cmds
            ]
        groups[:] = [g for g in groups if g["hooks"]]
        if not groups:
            del settings["hooks"][event]


def merge_settings(existing: dict, template: dict) -> dict:
    """Union permissions; add tack hook groups whose commands aren't already present.

    The user's own entries are never touched; outdated tack entries are removed.
    """
    out = json.loads(json.dumps(existing))  # deep copy
    _prune_tack_entries(out, template)
    for key, value in template.items():
        if key == "permissions":
            perms = out.setdefault("permissions", {})
            for list_name, items in value.items():
                cur = perms.setdefault(list_name, [])
                cur += [i for i in items if i not in cur]
        elif key == "hooks":
            hooks = out.setdefault("hooks", {})
            for event, groups in value.items():
                cur = hooks.setdefault(event, [])
                have = _hook_commands(cur)
                cur += [g for g in groups if not _hook_commands([g]) <= have]
        else:
            out.setdefault(key, value)
    return out


# --------------------------------------------------------------------------- install


def install(
    root: Path, files: list[Planned], force: bool = False, dry_run: bool = False
) -> list[Action]:
    root = root.resolve()
    lock = read_lock(root)
    locked: dict[str, str] = lock.get("files", {})
    actions: list[Action] = []

    for f in files:
        target = root / f.path
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        new: str | None = f.content
        verb = "created" if current is None else "updated"
        note = ""

        if current is not None:
            if f.kind == "seed":
                new, verb = None, "unchanged"
            elif f.kind == "block":
                new = merge_block(current, f.content)
                verb = "merged"
            elif f.kind == "merge":
                try:
                    existing = json.loads(current)
                    merged = merge_settings(existing, json.loads(f.content))
                    if merged == existing:
                        new, verb = None, "unchanged"
                    else:
                        new, verb = json.dumps(merged, indent=2) + "\n", "merged"
                except json.JSONDecodeError:
                    new, verb, note = None, "kept", "existing file is not valid JSON"
            elif current == f.content:
                new, verb = None, "unchanged"
            elif not force and locked.get(f.path) != _sha(current):
                new, verb = None, "kept"
                note = "you changed this file; use --force to replace it"

        if new is not None and new == current:
            new, verb = None, "unchanged"
        if new is not None and not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding="utf-8")
        if f.kind == "managed" and verb in ("created", "updated", "unchanged"):
            locked[f.path] = _sha(new if new is not None else current or "")
        actions.append(Action(verb, f.path, note))

    # Files tack used to manage but no longer ships: remove them if the user never edited them.
    planned = {f.path for f in files}
    for path in sorted(set(locked) - planned):
        target = root / path
        if target.is_file() and _sha(target.read_text(encoding="utf-8")) != locked[path]:
            actions.append(Action("kept", path, "no longer used by tack; you edited it"))
        elif target.is_file():
            if not dry_run:
                target.unlink()
            actions.append(Action("removed", path, "no longer used by tack"))
        del locked[path]

    if not dry_run:
        write_lock(root, {"version": runtime.RUNTIME_VERSION, "files": locked})
    return actions
