from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import PY, fail_cmd, git, make_manifest, ok_cmd, write

from tack import runtime


def test_pass_fail_skip(tmp_path: Path) -> None:
    m = make_manifest(
        tmp_path,
        [
            {
                "name": "a",
                "path": ".",
                "stack": "x",
                "commands": {"lint": ok_cmd(), "test": fail_cmd("nope")},
            }
        ],
    )
    results = runtime.verify(m, ("lint", "typecheck", "test"))
    assert [(r.check, r.status) for r in results] == [
        ("lint", "pass"),
        ("typecheck", "skip"),
        ("test", "fail"),
    ]
    assert "nope" in results[2].output
    assert not runtime.passed(results)


def test_format_check_never_runs_mutating_format(tmp_path: Path) -> None:
    m = make_manifest(
        tmp_path,
        [
            {
                "name": "a",
                "path": ".",
                "stack": "x",
                "commands": {"format": fail_cmd(), "format_check": ok_cmd()},
            }
        ],
    )
    (r,) = runtime.verify(m, ("format",))
    assert r.status == "pass" and r.command == ok_cmd()


def test_fail_fast(tmp_path: Path) -> None:
    m = make_manifest(
        tmp_path,
        [
            {
                "name": "a",
                "path": ".",
                "stack": "x",
                "commands": {"lint": fail_cmd(), "test": ok_cmd()},
            }
        ],
    )
    results = runtime.verify(m, ("lint", "test"), fail_fast=True)
    assert [r.check for r in results] == ["lint"]


def test_timeout_is_error(tmp_path: Path) -> None:
    slow = f'"{PY}" -c "import time; time.sleep(5)"'
    m = make_manifest(
        tmp_path, [{"name": "a", "path": ".", "stack": "x", "commands": {"test": slow}}]
    )
    (r,) = runtime.verify(m, ("test",), timeout=1)
    assert r.status == "error"


def test_commands_run_in_component_dir(tmp_path: Path) -> None:
    write(tmp_path, "sub/marker.txt", "hi")
    script = "import pathlib, sys; sys.exit(0 if pathlib.Path('marker.txt').exists() else 1)"
    check = f'"{PY}" -c "{script}"'
    m = make_manifest(
        tmp_path, [{"name": "s", "path": "sub", "stack": "x", "commands": {"test": check}}]
    )
    assert runtime.passed(runtime.verify(m, ("test",)))


def test_changed_only_selects_touched_components(repo: Path) -> None:
    write(repo, "a/x.txt", "1")
    write(repo, "b/y.txt", "1")
    m = make_manifest(
        repo,
        [
            {"name": "a", "path": "a", "stack": "x", "commands": {"test": ok_cmd()}},
            {"name": "b", "path": "b", "stack": "x", "commands": {"test": ok_cmd()}},
        ],
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    write(repo, "b/y.txt", "2")
    results = runtime.verify(m, ("test",), changed_only=True)
    assert [r.component for r in results] == ["b"]


def test_component_for_picks_most_specific(tmp_path: Path) -> None:
    m = make_manifest(
        tmp_path,
        [
            {"name": "root", "path": ".", "stack": "x"},
            {"name": "api", "path": "services/api", "stack": "x"},
        ],
    )
    assert m.component_for(tmp_path / "services/api/main.py").name == "api"
    assert m.component_for(tmp_path / "README.md").name == "root"
    assert m.component_for(Path("/elsewhere/file")) is None


def test_cli_json_and_exit_code(tmp_path: Path, monkeypatch, capsys) -> None:
    make_manifest(
        tmp_path, [{"name": "a", "path": ".", "stack": "x", "commands": {"test": fail_cmd()}}]
    )
    monkeypatch.chdir(tmp_path)
    assert runtime.main(["verify", "--only", "test", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["results"][0]["status"] == "fail"


def test_cli_rejects_unknown_check(tmp_path: Path, monkeypatch) -> None:
    make_manifest(tmp_path, [])
    monkeypatch.chdir(tmp_path)
    assert runtime.main(["verify", "--only", "vibes"]) == 2


def test_missing_manifest_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        runtime.load_manifest()
