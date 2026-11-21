from __future__ import annotations

import json
from pathlib import Path

from conftest import make_manifest, ok_cmd, write

from tack import cli, doctor, install, runtime


def levels(findings: list[doctor.Finding]) -> dict[str, str]:
    return {f.message: f.level for f in findings}


def test_executable_of() -> None:
    assert doctor.executable_of("uv run pytest -q") == "uv"
    assert doctor.executable_of("FOO=1 BAR=2 npm test") == "npm"
    assert doctor.executable_of('test -z "$(gofmt -l .)"') is None
    assert doctor.executable_of("./gradlew test") == "./gradlew"


def test_doctor_healthy_project(tmp_path: Path) -> None:
    write(tmp_path, "Makefile", "test:\n\ttrue\nlint:\n\ttrue\n")
    cli.main(["init", str(tmp_path)])
    (tmp_path / ".git").mkdir()
    findings = doctor.check(tmp_path)
    assert not [f for f in findings if f.level == "fail"]
    assert any("vendored runtime is current" in f.message for f in findings)
    assert any("hooks wired" in f.message for f in findings)


def test_doctor_flags_problems(tmp_path: Path) -> None:
    make_manifest(
        tmp_path,
        [
            {"name": "gone", "path": "missing-dir", "stack": "x", "commands": {"test": ok_cmd()}},
            {
                "name": "app",
                "path": ".",
                "stack": "x",
                "commands": {"test": "no-such-tool-xyz run"},
            },
        ],
    )
    findings = doctor.check(tmp_path)
    msgs = " | ".join(f.message for f in findings)
    assert "missing path ./missing-dir" in msgs
    assert "'no-such-tool-xyz' not found" in msgs
    assert "vendored runtime missing" in msgs
    assert any(f.level == "fail" for f in findings)


def test_doctor_stale_runtime(tmp_path: Path) -> None:
    cli.main(["init", str(tmp_path)])
    (tmp_path / ".claude/hooks/tack").write_text("# old")
    assert any("differs" in f.message for f in doctor.check(tmp_path))


def test_doctor_broken_manifest(tmp_path: Path) -> None:
    (tmp_path / "tack.toml").write_text("[[[")
    assert doctor.check(tmp_path)[-1].level == "fail"


# --------------------------------------------------------------------- add-ons


def test_ci_setup_steps_match_stacks() -> None:
    comps = [
        runtime.Component("api", "api", "python", {"test": "uv run pytest"}),
        runtime.Component("web", "web", "node", {"setup": "pnpm install"}),
        runtime.Component("svc", "svc", "go", {}),
    ]
    steps = install.ci_setup_steps(comps)
    assert "setup-uv" in steps and "pnpm/action-setup" in steps and "setup-go" in steps
    assert "rust-toolchain" not in steps
    assert steps.index("pnpm/action-setup") < steps.index("setup-node")


def test_add_ci_renders_workflow_and_records_addon(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path, "Cargo.toml", '[package]\nname="x"\n')
    cli.main(["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["add", "ci"]) == 0
    wf = (tmp_path / ".github/workflows/tack-verify.yml").read_text()
    assert "rust-toolchain" in wf and "{{setup_steps}}" not in wf
    assert "${{ github.ref }}" in wf  # GitHub expressions survive rendering
    assert runtime.read_manifest_data(tmp_path)["project"]["addons"] == ["ci"]
    # update keeps managing the add-on
    (tmp_path / ".github/workflows/tack-verify.yml").unlink()
    cli.main(["update", str(tmp_path)])
    assert (tmp_path / ".github/workflows/tack-verify.yml").is_file()


def test_add_unknown_addon(tmp_path: Path, monkeypatch) -> None:
    cli.main(["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["add", "nope"]) == 2


def test_claude_github_addon_files(tmp_path: Path, monkeypatch) -> None:
    cli.main(["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    cli.main(["add", "claude-github"])
    for name in ("claude.yml", "claude-review.yml"):
        text = (tmp_path / ".github/workflows" / name).read_text()
        assert "anthropics/claude-code-action@v1" in text
        assert "${{ secrets.ANTHROPIC_API_KEY }}" in text


def test_markdown_report(tmp_path: Path, monkeypatch, capsys) -> None:
    make_manifest(
        tmp_path, [{"name": "a", "path": ".", "stack": "x", "commands": {"test": ok_cmd()}}]
    )
    monkeypatch.chdir(tmp_path)
    assert runtime.main(["verify", "--only", "test,lint", "--markdown"]) == 0
    out = capsys.readouterr().out
    assert "### tack verify: passed" in out and "| ✅ | a | test |" in out


def test_doctor_cli_json(tmp_path: Path, monkeypatch, capsys) -> None:
    cli.main(["init", str(tmp_path)])
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    cli.main(["doctor", "--json"])
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_template_action_versions_match_repo_workflows() -> None:
    """Dependabot bumps .github/workflows but can't see the add-on templates; this test
    fails on its PRs until the templates are bumped too."""
    import re

    root = Path(__file__).resolve().parent.parent
    pattern = re.compile(r"([\w.-]+/[\w.-]+)@(v\d+)")

    def versions(paths: list[Path]) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for p in paths:
            for action, ver in pattern.findall(p.read_text(encoding="utf-8")):
                found.setdefault(action, set()).add(ver)
        return found

    repo = versions(list((root / ".github/workflows").glob("*.yml")))
    templates = versions(
        [*(root / "src/tack/templates/addons").rglob("*.yml*"), root / "src/tack/install.py"]
    )
    for action in repo.keys() & templates.keys():
        assert templates[action] == repo[action], f"{action}: {templates[action]} vs {repo[action]}"
