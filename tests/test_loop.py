from __future__ import annotations

import json
from pathlib import Path

from conftest import PY, git, make_manifest, write

from tack import cli, loop, runtime

# A fake agent: first attempt writes a bug, later attempts fix it. Records every prompt.
FAKE_AGENT = """
import json, pathlib, sys
prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
state = pathlib.Path("attempts.txt")
n = int(state.read_text()) + 1 if state.exists() else 1
state.write_text(str(n))
with open("prompts.jsonl", "a") as fh:
    fh.write(json.dumps(prompt) + "\\n")
pathlib.Path("answer.txt").write_text("good" if n >= {fix_on} else "bad")
print(json.dumps({{"result": f"attempt {{n}} done", "total_cost_usd": 0.01}}))
"""

CHECK = f"\"{PY}\" -c \"import sys; sys.exit(open('answer.txt').read() != 'good')\""


def setup_project(root: Path, fix_on: int = 2) -> runtime.Manifest:
    write(root, "agent.py", FAKE_AGENT.format(fix_on=fix_on))
    return make_manifest(
        root, [{"name": "app", "path": ".", "stack": "x", "commands": {"test": CHECK}}]
    )


def agent_cmd(root: Path, use_stdin: bool = False) -> str:
    base = f'"{PY}" "{root / "agent.py"}"'
    return base if use_stdin else base + " {prompt}"


def prompts(root: Path) -> list[str]:
    return [json.loads(line) for line in (root / "prompts.jsonl").read_text().splitlines()]


def test_loop_retries_with_failures_then_passes(tmp_path: Path) -> None:
    m = setup_project(tmp_path, fix_on=2)
    result = loop.run_loop(
        m,
        "make answer good",
        agent=agent_cmd(tmp_path),
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    assert result.status == "passed"
    assert [i.verify_ok for i in result.iterations] == [False, True]
    assert result.cost_usd == 0.02
    first, second = prompts(tmp_path)
    assert first.startswith("make answer good") and "verify" in first
    assert "checks failed" in second and "app:test" in second


def test_loop_stops_at_iteration_limit(tmp_path: Path) -> None:
    m = setup_project(tmp_path, fix_on=99)
    result = loop.run_loop(
        m,
        "never works",
        agent=agent_cmd(tmp_path),
        max_iters=3,
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    assert result.status == "failed" and len(result.iterations) == 3


def test_loop_passes_prompt_on_stdin_without_placeholder(tmp_path: Path) -> None:
    m = setup_project(tmp_path, fix_on=1)
    result = loop.run_loop(
        m,
        "via stdin",
        agent=agent_cmd(tmp_path, use_stdin=True),
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    assert result.status == "passed"
    assert prompts(tmp_path)[0].startswith("via stdin")


def test_loop_reports_missing_agent(tmp_path: Path) -> None:
    m = setup_project(tmp_path)
    result = loop.run_loop(
        m,
        "x",
        agent="definitely-not-a-real-agent-xyz {prompt}",
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    assert result.status == "agent_error" and len(result.iterations) == 1


def test_loop_agent_timeout(tmp_path: Path) -> None:
    m = setup_project(tmp_path)
    hang = f'"{PY}" -c "import time; time.sleep(30)"'
    result = loop.run_loop(
        m,
        "x",
        agent=hang,
        max_iters=1,
        agent_timeout=1,
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    assert result.iterations[0].agent_exit is None


def test_run_log_and_runs_listing(tmp_path: Path) -> None:
    m = setup_project(tmp_path, fix_on=1)
    result = loop.run_loop(
        m,
        "Log Me Please!",
        agent=agent_cmd(tmp_path),
        checks=("test",),
        changed_only=False,
        echo=False,
    )
    events = [
        json.loads(line)["event"] for line in (tmp_path / result.log_path).read_text().splitlines()
    ]
    assert events == ["start", "agent", "verify", "end"]
    assert "log-me-please" in result.log_path
    (run,) = loop.list_runs(tmp_path)
    assert run["status"] == "passed" and run["task"] == "Log Me Please!"


def test_parse_agent_output() -> None:
    assert loop.parse_agent_output('{"result": "hi", "total_cost_usd": 0.5}') == ("hi", 0.5)
    assert loop.parse_agent_output("plain text") == ("plain text", None)
    assert loop.parse_agent_output("{broken") == ("{broken", None)


def test_cli_loop_refuses_new_project(tmp_path: Path, monkeypatch) -> None:
    cli.main(["new", str(tmp_path / "p")])
    monkeypatch.chdir(tmp_path / "p")
    assert cli.main(["loop", "anything"]) == 2


def test_cli_loop_json(tmp_path: Path, monkeypatch, capsys) -> None:
    setup_project(tmp_path, fix_on=1)
    monkeypatch.chdir(tmp_path)
    code = cli.main(
        ["loop", "go", "--agent", agent_cmd(tmp_path), "--only", "test", "--all", "--json"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_loop_no_changes_is_not_a_free_pass(repo: Path) -> None:
    """An agent that changes nothing must not 'pass' just because no component changed."""
    write(repo, "answer.txt", "bad")
    make_manifest(repo, [{"name": "app", "path": ".", "stack": "x", "commands": {"test": CHECK}}])
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    m = runtime.load_manifest(repo)
    noop = f'"{PY}" -c "pass"'
    result = loop.run_loop(m, "x", agent=noop, max_iters=1, checks=("test",), echo=False)
    assert result.status == "failed"


def test_parse_agent_output_skips_leading_warnings() -> None:
    out = 'Warning: workspace not trusted\n{"result": "fixed it", "total_cost_usd": 0.03}\n'
    assert loop.parse_agent_output(out) == ("fixed it", 0.03)
