from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import write

from tack import cli, install, runtime


def actions_by_path(actions: list[install.Action]) -> dict[str, str]:
    return {a.path: a.verb for a in actions}


def test_init_creates_everything(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module x\n")
    assert cli.main(["init", str(tmp_path)]) == 0
    for rel in [
        "tack.toml",
        "AGENTS.md",
        "CLAUDE.md",
        "PROGRESS.md",
        ".claude/settings.json",
        ".claude/hooks/tack",
        ".claude/skills/plan/SKILL.md",
        ".claude/agents/reviewer.md",
        ".tack/lock.json",
        ".tack/.gitignore",
    ]:
        assert (tmp_path / rel).is_file(), rel
    assert not (tmp_path / "SPEC.md").exists()  # only `new` seeds a spec
    assert runtime.load_manifest(tmp_path).components[0].stack == "go"


def test_init_is_idempotent(tmp_path: Path) -> None:
    files = install.plan(install.context_for(tmp_path))
    install.install(tmp_path, files)
    again = install.install(tmp_path, files)
    assert {a.verb for a in again} == {"unchanged"}


def test_update_keeps_user_edits_and_refreshes_untouched(tmp_path: Path) -> None:
    ctx = install.context_for(tmp_path)
    install.install(tmp_path, install.plan(ctx))
    edited = tmp_path / ".claude/skills/plan/SKILL.md"
    edited.write_text("my own plan skill")

    # simulate a newer tack shipping different content for two files
    newer = [
        install.Planned(f.path, f.content + "\n<!-- v2 -->", f.kind)
        if f.path in (".claude/skills/plan/SKILL.md", ".claude/skills/build/SKILL.md")
        else f
        for f in install.plan(ctx)
    ]
    verbs = actions_by_path(install.install(tmp_path, newer))
    assert verbs[".claude/skills/plan/SKILL.md"] == "kept"
    assert edited.read_text() == "my own plan skill"
    assert verbs[".claude/skills/build/SKILL.md"] == "updated"

    install.install(tmp_path, newer, force=True)
    assert "v2" in edited.read_text()


def test_existing_agents_md_keeps_user_text(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "# My project\n\nHand-written notes.\n")
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# My project\n\nHand-written notes.")
    assert text.count("<!-- tack:begin") == 1
    # updating again replaces the block in place instead of appending a second one
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    assert (tmp_path / "AGENTS.md").read_text().count("<!-- tack:begin") == 1


def test_settings_merge_preserves_user_config(tmp_path: Path) -> None:
    user = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]},
    }
    write(tmp_path, ".claude/settings.json", json.dumps(user))
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))  # twice: no dupes
    merged = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert merged["model"] == "opus"
    assert merged["permissions"]["allow"][0] == "Bash(ls:*)"
    stop_cmds = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_cmds[0] == "say done" and len(stop_cmds) == 2
    assert len(merged["hooks"]["PreToolUse"]) == 2


def test_invalid_settings_json_is_left_alone(tmp_path: Path) -> None:
    write(tmp_path, ".claude/settings.json", "{ not json")
    verbs = actions_by_path(install.install(tmp_path, install.plan(install.context_for(tmp_path))))
    assert verbs[".claude/settings.json"] == "kept"


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    install.install(tmp_path, install.plan(install.context_for(tmp_path)), dry_run=True)
    assert list(tmp_path.iterdir()) == []


def test_new_creates_bootstrappable_project(tmp_path: Path) -> None:
    target = tmp_path / "my-app"
    assert cli.main(["new", str(target)]) == 0
    m = runtime.load_manifest(target)
    assert m.status == "new" and m.components == []
    assert (target / "SPEC.md").read_text().startswith("# my-app")
    assert (target / ".claude/skills/bootstrap/SKILL.md").is_file()


def test_new_refuses_non_empty_dir(tmp_path: Path) -> None:
    write(tmp_path, "existing.txt")
    assert cli.main(["new", str(tmp_path)]) == 2


def test_vendored_runtime_works_standalone(tmp_path: Path) -> None:
    """The copied runtime must run with nothing but the Python stdlib."""
    write(tmp_path, "go.mod", "module x\n")
    cli.main(["init", str(tmp_path)])
    vendored = tmp_path / ".claude/hooks/tack"
    out = subprocess.run(
        [sys.executable, "-I", str(vendored), "detect", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(out.stdout)[0]["stack"] == "go"
    out = subprocess.run(
        [sys.executable, "-I", str(vendored), "hook", "guard-bash"],
        input=json.dumps({"cwd": str(tmp_path), "tool_input": {"command": "rm -rf /"}}),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_templates_have_valid_skill_frontmatter() -> None:
    skills = list((install.TEMPLATES / "core/dot-claude/skills").glob("*/SKILL.md"))
    agents = list((install.TEMPLATES / "core/dot-claude/agents").glob("*.md"))
    assert len(skills) == 7 and len(agents) == 3
    for f in skills + agents:
        text = f.read_text()
        assert text.startswith("---\nname: "), f
        name = text.split("\n")[1].removeprefix("name: ")
        assert name == (f.parent.name if f.name == "SKILL.md" else f.stem), f
        assert "\ndescription: " in text.split("---")[1], f


def test_dropped_files_are_removed_unless_edited(tmp_path: Path) -> None:
    ctx = install.context_for(tmp_path)
    files = install.plan(ctx)
    extra = [
        install.Planned("old/unused.md", "old", "managed"),
        install.Planned("old/edited.md", "old", "managed"),
    ]
    install.install(tmp_path, files + extra)
    (tmp_path / "old/edited.md").write_text("mine now")
    verbs = actions_by_path(install.install(tmp_path, files))
    assert verbs["old/unused.md"] == "removed" and not (tmp_path / "old/unused.md").exists()
    assert verbs["old/edited.md"] == "kept" and (tmp_path / "old/edited.md").exists()
    assert "old/edited.md" not in install.read_lock(tmp_path)["files"]


def test_outdated_tack_hooks_are_replaced_not_duplicated(tmp_path: Path) -> None:
    legacy = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .claude/hooks/tack_runtime.py hook stop-verify",
                        },
                        {"type": "command", "command": "say done"},
                    ]
                }
            ]
        },
        "permissions": {"allow": ["Bash(python3 .claude/hooks/tack_runtime.py verify:*)"]},
    }
    write(tmp_path, ".claude/settings.json", json.dumps(legacy))
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    merged = json.loads((tmp_path / ".claude/settings.json").read_text())
    stop = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
    assert "say done" in stop
    assert not any("tack_runtime.py" in c for c in stop)
    assert sum("hook stop-verify" in c for c in stop) == 1
    assert not any("tack_runtime.py" in p for p in merged["permissions"]["allow"])


def test_vendored_runtime_is_invisible_to_python_tooling(tmp_path: Path) -> None:
    """Linters, formatters and test runners only scan *.py, so the runtime has no suffix."""
    install.install(tmp_path, install.plan(install.context_for(tmp_path)))
    assert (tmp_path / ".claude/hooks/tack").is_file()
    assert not list((tmp_path / ".claude").rglob("*.py"))
