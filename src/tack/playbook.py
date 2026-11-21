"""`tack playbook`: connect, sync, and inspect a playbook (stacks + skill routing)."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import runtime


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    path: Path
    message: str


def sync(source: str) -> SyncResult:
    """Clone or fast-forward a remote playbook into the cache. Local paths need no sync."""
    path = runtime.playbook_path(source)
    if not runtime.is_remote(source):
        ok = path.is_dir()
        return SyncResult(ok, path, "local folder" if ok else f"{path} does not exist")
    if not shutil.which("git"):
        return SyncResult(False, path, "git is not installed")
    if (path / ".git").is_dir():
        cmd = ["git", "-C", str(path), "pull", "--ff-only", "--quiet"]
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1", "--quiet", runtime.remote_url(source), str(path)]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, **runtime.TEXT)
    if proc.returncode != 0:
        return SyncResult(False, path, (proc.stderr or proc.stdout).strip() or "git failed")
    return SyncResult(True, path, "updated" if "pull" in cmd else "cloned")


def set_user_source(source: str) -> Path:
    """Remember the playbook for every project on this machine."""
    path = runtime.user_config_path()
    data = runtime.read_user_config()
    data.setdefault("playbook", {})["source"] = source
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# tack user config: applies to every project on this machine."
    path.write_text(runtime.dump_toml(data, header), encoding="utf-8")
    return path


def set_project_source(root: Path, source: str) -> None:
    data = runtime.read_manifest_data(root)
    data.setdefault("playbook", {})["source"] = source
    (root / runtime.MANIFEST).write_text(
        runtime.dump_toml(data, runtime.MANIFEST_HEADER), encoding="utf-8"
    )


def normalize(source: str) -> str:
    """Accept owner/repo shorthand and relative paths."""
    if runtime.is_remote(source):
        return source
    if (
        "/" in source
        and not Path(source).expanduser().exists()
        and source.count("/") == 1
        and not source.startswith((".", "/", "~"))
    ):
        return f"github:{source}"
    return str(Path(source).expanduser().resolve())


def age_days(path: Path) -> float | None:
    """Days since the cached playbook was last fetched (None for local folders)."""
    for marker in (path / ".git" / "FETCH_HEAD", path / ".git" / "HEAD"):
        if marker.exists():
            return (time.time() - marker.stat().st_mtime) / 86400
    return None


def route_status(routes: list[dict], root: Path) -> list[tuple[dict, str | None]]:
    plugins = runtime.installed_plugins()
    return [(r, runtime.resolve_route_target(r, root, plugins)) for r in routes]


def install_hint(r: dict) -> str:
    if r.get("plugin"):
        return f"/plugin install {r['plugin']}"
    if r.get("project"):
        return "tack init (or install the tack plugin)"
    return "see the playbook's skills.md for the source"
