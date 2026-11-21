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

BLOCK_FILES = {"AGENTS.md"}
MERGE_FILES = {".claude/settings.json"}


@dataclass(frozen=True)
class Planned:
    path: str  # relative to project root, posix
    content: str
    kind: str  # managed | block | merge | seed


@dataclass(frozen=True)
class Action:
    verb: str  # created | updated | merged | kept | unchanged
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


def plan(context: dict[str, str], seeds: tuple[str, ...] = ("PROGRESS.md",)) -> list[Planned]:
    files: list[Planned] = []
    core = TEMPLATES / "core"
    for src in sorted(p for p in core.rglob("*") if p.is_file()):
        dest = _dest(src.relative_to(core))
        kind = "block" if dest in BLOCK_FILES else "merge" if dest in MERGE_FILES else "managed"
        files.append(Planned(dest, render(src.read_text(encoding="utf-8"), context), kind))
    runtime_src = Path(runtime.__file__).read_text(encoding="utf-8")
    files.append(Planned(".claude/hooks/tack_runtime.py", runtime_src, "managed"))
    seed_dir = TEMPLATES / "seed"
    for src in sorted(seed_dir.glob("*.tmpl")):
        dest = _dest(src.relative_to(seed_dir))
        if dest in seeds:
            files.append(Planned(dest, render(src.read_text(encoding="utf-8"), context), "seed"))
    return files


def context_for(root: Path, name: str | None = None) -> dict[str, str]:
    return {"name": name or root.resolve().name, "date": _dt.date.today().isoformat()}


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


def merge_settings(existing: dict, template: dict) -> dict:
    """Union permissions; add tack hook groups whose commands aren't already present."""
    out = json.loads(json.dumps(existing))  # deep copy
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

    if not dry_run:
        write_lock(root, {"version": runtime.RUNTIME_VERSION, "files": locked})
    return actions
