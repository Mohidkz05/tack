from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tack import runtime

PY = sys.executable


def write(root: Path, rel: str, text: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_manifest(root: Path, components: list[dict], **extra) -> runtime.Manifest:
    data = runtime.default_manifest(root.name)
    data["components"] = components
    data.update(extra)
    (root / runtime.MANIFEST).write_text(runtime.dump_toml(data), encoding="utf-8")
    return runtime.load_manifest(root)


def ok_cmd() -> str:
    return f'"{PY}" -c "pass"'


def fail_cmd(msg: str = "boom") -> str:
    return f'"{PY}" -c "import sys; print(\'{msg}\'); sys.exit(1)"'


def hook(name: str, event: dict) -> dict | None:
    """Run a hook in-process and return its parsed JSON output (None if silent)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        runtime.run_hook(name, json.dumps(event))
    out = buf.getvalue().strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"text": out}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    return root
