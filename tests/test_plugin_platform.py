from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import hook, make_manifest, write

from tack import cli, loop, runtime

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_is_in_sync_with_templates() -> None:
    """plugin/ is generated from the templates; CI fails if someone forgets to rebuild."""
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_plugin.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout


def test_plugin_hooks_use_plugin_root_and_flag() -> None:
    hooks = json.loads((ROOT / "plugin/hooks/hooks.json").read_text())["hooks"]
    cmds = [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]
    assert cmds and all(
        "${CLAUDE_PLUGIN_ROOT}/hooks/tack" in c and c.endswith("--plugin") for c in cmds
    )


def test_plugin_skills_point_at_plugin_runtime() -> None:
    for skill in (ROOT / "plugin/skills").glob("*/SKILL.md"):
        assert ".claude/hooks/tack " not in skill.read_text(), skill


def test_plugin_hook_defers_to_vendored_copy(tmp_path: Path) -> None:
    event = {"cwd": str(tmp_path), "tool_input": {"command": "rm -rf /"}}
    make_manifest(tmp_path, [])
    import contextlib
    import io

    def run(from_plugin: bool) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runtime.run_hook("guard-bash", json.dumps(event), from_plugin=from_plugin)
        return buf.getvalue()

    assert "deny" in run(from_plugin=True)  # no vendored copy: the plugin guards
    write(tmp_path, ".claude/hooks/tack", "# vendored")
    assert run(from_plugin=True) == ""  # vendored copy present: plugin stays out of the way
    assert "deny" in hook("guard-bash", event)["hookSpecificOutput"]["permissionDecision"]


def test_session_start_names_the_right_runtime(tmp_path: Path) -> None:
    make_manifest(tmp_path, [])
    # no vendored copy (e.g. plugin-only): point at wherever this runtime file lives
    assert Path(runtime.__file__).resolve().as_posix() in runtime.self_command(tmp_path)
    write(tmp_path, ".claude/hooks/tack", "")
    assert runtime.self_command(tmp_path) == "python3 .claude/hooks/tack"


def test_agent_prompt_is_passed_as_one_exact_argument() -> None:
    prompt = 'line one\nline "two" with $HOME and `ticks`'
    argv, stdin = loop.build_command('my-agent -p {prompt} --flag "a b"', prompt)
    assert argv == ["my-agent", "-p", prompt, "--flag", "a b"] and stdin is None
    argv, stdin = loop.build_command("my-agent --stdin", prompt)
    assert argv == ["my-agent", "--stdin"] and stdin == prompt


def test_cli_survives_unencodable_output(tmp_path: Path, monkeypatch) -> None:
    import io

    class Ascii(io.TextIOWrapper):
        pass

    raw = io.BytesIO()
    stream = Ascii(raw, encoding="ascii")
    cli.main(["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdout", stream)
    assert cli.main(["doctor"]) in (0, 1)  # ✓ / ✗ must not raise UnicodeEncodeError
