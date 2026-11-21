from __future__ import annotations

import json
from pathlib import Path

from conftest import write

from tack import runtime


def by_name(root: Path) -> dict[str, runtime.Component]:
    return {c.name: c for c in runtime.detect(root)}


def test_python_uv_project(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname="x"\n[dependency-groups]\ndev=["mypy","pytest"]\n',
    )
    write(tmp_path, "uv.lock")
    (comp,) = runtime.detect(tmp_path)
    assert comp.stack == "python" and comp.path == "."
    assert comp.commands["lint"] == "uv run ruff check ."
    assert comp.commands["typecheck"] == "uv run mypy ."
    assert comp.commands["test"] == "uv run pytest -q"
    assert "{file}" in comp.commands["format_file"]


def test_python_black_and_pip(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "black\npytest\n")
    (comp,) = runtime.detect(tmp_path)
    assert comp.commands["setup"] == "pip install -r requirements.txt"
    assert comp.commands["format_check"] == "python -m black --check ."


def test_node_pnpm_typescript(tmp_path: Path) -> None:
    pkg = {"scripts": {"lint": "eslint .", "test": "vitest"}, "devDependencies": {"prettier": "3"}}
    write(tmp_path, "package.json", json.dumps(pkg))
    write(tmp_path, "pnpm-lock.yaml")
    write(tmp_path, "tsconfig.json", "{}")
    (comp,) = runtime.detect(tmp_path)
    assert comp.stack == "node"
    assert comp.commands["setup"] == "pnpm install --frozen-lockfile"
    assert comp.commands["lint"] == "pnpm run lint"
    assert comp.commands["typecheck"] == "pnpm exec tsc --noEmit"
    assert comp.commands["format_check"] == "pnpm exec prettier --check ."


def test_node_default_test_script_ignored(tmp_path: Path) -> None:
    pkg = {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
    write(tmp_path, "package.json", json.dumps(pkg))
    (comp,) = runtime.detect(tmp_path)
    assert "test" not in comp.commands


def test_go_and_golangci(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module x\n")
    write(tmp_path, ".golangci.yml")
    (comp,) = runtime.detect(tmp_path)
    assert comp.commands["lint"] == "golangci-lint run"
    assert comp.commands["test"] == "go test ./..."


def test_rust_workspace_members_not_duplicated(tmp_path: Path) -> None:
    write(tmp_path, "Cargo.toml", '[workspace]\nmembers=["crates/*"]\n')
    write(tmp_path, "crates/a/Cargo.toml", '[package]\nname="a"\n')
    comps = runtime.detect(tmp_path)
    assert [c.path for c in comps] == ["."]


def test_polyglot_monorepo(tmp_path: Path) -> None:
    write(tmp_path, "api/pyproject.toml", "[project]\nname='api'\n")
    write(tmp_path, "web/package.json", "{}")
    write(tmp_path, "svc/go.mod", "module svc\n")
    write(tmp_path, "web/node_modules/dep/package.json", "{}")  # ignored dir
    comps = by_name(tmp_path)
    assert {n: c.stack for n, c in comps.items()} == {"api": "python", "web": "node", "svc": "go"}


def test_java_gradle_wrapper(tmp_path: Path) -> None:
    write(tmp_path, "build.gradle.kts", 'plugins { id("com.diffplug.spotless") }')
    write(tmp_path, "gradlew")
    (comp,) = runtime.detect(tmp_path)
    assert comp.commands["test"] == "./gradlew test"
    assert comp.commands["format_check"] == "./gradlew spotlessCheck"


def test_makefile_generic_fallback(tmp_path: Path) -> None:
    write(tmp_path, "Makefile", "lint:\n\techo\ntest:\n\techo\nVAR := 1\n")
    (comp,) = runtime.detect(tmp_path)
    assert comp.stack == "generic"
    assert comp.commands == {"lint": "make lint", "test": "make test"}


def test_makefile_fills_gaps_for_stack(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module x\n")
    write(tmp_path, "Makefile", "typecheck:\n\techo\ntest:\n\techo\n")
    (comp,) = runtime.detect(tmp_path)
    assert comp.commands["typecheck"] == "make typecheck"
    assert comp.commands["test"] == "go test ./..."  # stack wins over Makefile


def test_merge_keeps_user_commands(tmp_path: Path) -> None:
    existing = [{"name": "app", "path": ".", "stack": "python", "commands": {"test": "pytest -x"}}]
    detected = [
        runtime.Component("app", ".", "python", {"test": "pytest -q", "lint": "ruff"}),
        runtime.Component("web", "web", "node", {"test": "npm test"}),
    ]
    merged = runtime.merge_components(existing, detected)
    assert merged[0]["commands"] == {"test": "pytest -x", "lint": "ruff"}
    assert merged[1]["name"] == "web"


def test_write_detected_activates_new_project(tmp_path: Path) -> None:
    data = runtime.default_manifest("x", status="new")
    (tmp_path / "tack.toml").write_text(runtime.dump_toml(data))
    write(tmp_path, "go.mod", "module x\n")
    runtime.write_detected(tmp_path)
    m = runtime.load_manifest(tmp_path)
    assert m.status == "active"
    assert m.components[0].stack == "go"


def test_toml_round_trip(tmp_path: Path) -> None:
    data = runtime.default_manifest('we"ird name')
    data["components"] = [
        {
            "name": "a",
            "path": ".",
            "stack": "go",
            "commands": {"format_check": 'test -z "$(gofmt -l .)"'},
        }
    ]
    (tmp_path / "tack.toml").write_text(runtime.dump_toml(data, runtime.MANIFEST_HEADER))
    assert runtime.read_manifest_data(tmp_path) == data
