"""`tack loop`: run an agent, verify, feed failures back, repeat, and log every step.

The agent is any command line tool. `{prompt}` in the command is replaced with the
shell-quoted prompt; without it, the prompt goes to the agent's stdin. That makes the
loop agent-agnostic: Claude Code by default, but also Codex, Gemini, Aider, or a script.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import runtime

DEFAULT_AGENT = "claude -p {prompt} --permission-mode acceptEdits --output-format json"
RUNS_DIR = Path(".tack") / "runs"
AGENT_NOT_FOUND = (126, 127, 9009)  # POSIX "not executable" / "not found", Windows cmd

FIRST_PROMPT = """\
{task}

Work in this repository following AGENTS.md. Keep the change focused on the task.
You are done only when the project's checks pass:
    python3 .claude/hooks/tack_runtime.py verify --changed
Before you stop, update PROGRESS.md with what you did."""

RETRY_PROMPT = """\
Your previous attempt at this task is not finished: the project's checks failed.

Task: {task}

Fix the root cause of these failures. Do not weaken, skip, or delete tests or lint rules.

{failures}"""


@dataclass
class Iteration:
    n: int
    agent_exit: int | None
    agent_seconds: float
    verify_ok: bool
    failures: list[str] = field(default_factory=list)
    cost_usd: float | None = None


@dataclass
class LoopResult:
    status: str  # passed | failed | agent_error | interrupted
    iterations: list[Iteration]
    seconds: float
    log_path: str
    cost_usd: float | None = None


class RunLog:
    """Append-only JSONL log of one loop run in .tack/runs/."""

    def __init__(self, root: Path, task: str) -> None:
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")[:40] or "task"
        self.path = root / RUNS_DIR / f"{stamp}-{slug}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **data: object) -> None:
        record = {
            "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            "event": event,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def build_command(template: str, prompt: str) -> tuple[str, str | None]:
    """Return (shell command, stdin text)."""
    if "{prompt}" in template:
        return template.replace("{prompt}", runtime.quote_path(prompt)), None
    return template, prompt


def parse_agent_output(output: str) -> tuple[str, float | None]:
    """Extract a readable result and cost from JSON agent output (e.g. Claude Code's
    `--output-format json`). Plain-text output is returned unchanged."""
    text = output.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return output, None
        if isinstance(data, dict):
            cost = data.get("total_cost_usd")
            return str(data.get("result", output)), float(cost) if cost is not None else None
    return output, None


def run_agent(
    cmd: str, stdin: str | None, cwd: Path, timeout: int, echo: bool
) -> tuple[int | None, str]:
    """Run the agent, streaming its output to the terminal while capturing it."""
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
    )
    if stdin is not None and proc.stdin:
        proc.stdin.write(stdin)
        proc.stdin.close()
    lines: list[str] = []

    def pump() -> None:  # read in a thread so a silent, hung agent still times out
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if echo and not line.lstrip().startswith("{"):
                sys.stdout.write("  │ " + line)
                sys.stdout.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        code = None
    reader.join(timeout=5)
    output = "".join(lines)
    if code is None:
        output += f"\n[tack] agent timed out after {timeout}s"
    return code, output


def run_loop(
    m: runtime.Manifest,
    task: str,
    agent: str | None = None,
    max_iters: int | None = None,
    checks: tuple[str, ...] = runtime.DEFAULT_VERIFY,
    changed_only: bool = True,
    agent_timeout: int = 1800,
    echo: bool = True,
) -> LoopResult:
    template = agent or m.agent.get("command") or DEFAULT_AGENT
    limit = max_iters or int(m.agent.get("max_iters", 5))
    log = RunLog(m.root, task)
    log.write("start", task=task, agent=template, max_iters=limit, checks=list(checks))
    iterations: list[Iteration] = []
    started = time.monotonic()
    prompt = FIRST_PROMPT.format(task=task)
    status = "failed"

    def say(msg: str) -> None:
        if echo:
            print(msg, flush=True)

    try:
        for n in range(1, limit + 1):
            say(f"\n[tack] iteration {n}/{limit}: running agent")
            cmd, stdin = build_command(template, prompt)
            t0 = time.monotonic()
            code, output = run_agent(cmd, stdin, m.root, agent_timeout, echo)
            agent_secs = round(time.monotonic() - t0, 1)
            result_text, cost = parse_agent_output(output)
            if echo and result_text is not output:
                print("  │ " + result_text.strip().replace("\n", "\n  │ "))
            log.write(
                "agent",
                iteration=n,
                command=cmd,
                exit_code=code,
                seconds=agent_secs,
                cost_usd=cost,
                output=runtime.tail(result_text, 200),
            )
            if code in AGENT_NOT_FOUND:
                say(f"[tack] agent command failed to start (exit {code}): {template}")
                iterations.append(Iteration(n, code, agent_secs, False, cost_usd=cost))
                status = "agent_error"
                break

            say(f"[tack] iteration {n}/{limit}: verifying")
            results = runtime.verify(m, checks, changed_only=changed_only)
            ok = runtime.passed(results)
            failures = [
                f"{r.component}:{r.check}" for r in results if r.status in ("fail", "error")
            ]
            log.write("verify", iteration=n, ok=ok, results=[asdict(r) for r in results])
            iterations.append(Iteration(n, code, agent_secs, ok, failures, cost))
            if results:
                say(runtime.summarize([r for r in results if r.status != "skip"]))
            if ok:
                status = "passed"
                break
            prompt = RETRY_PROMPT.format(
                task=task,
                failures=runtime.summarize([r for r in results if r.status in ("fail", "error")]),
            )
    except KeyboardInterrupt:
        status = "interrupted"

    costs = [i.cost_usd for i in iterations if i.cost_usd is not None]
    result = LoopResult(
        status,
        iterations,
        round(time.monotonic() - started, 1),
        str(log.path.relative_to(m.root)),
        round(sum(costs), 4) if costs else None,
    )
    log.write(
        "end",
        status=status,
        iterations=len(iterations),
        seconds=result.seconds,
        cost_usd=result.cost_usd,
    )
    return result


def list_runs(root: Path, limit: int = 10) -> list[dict]:
    """Summaries of the most recent runs, newest first."""
    runs = []
    for path in sorted((root / RUNS_DIR).glob("*.jsonl"), reverse=True)[:limit]:
        start: dict = {}
        end: dict = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "start":
                start = rec
            elif rec.get("event") == "end":
                end = rec
        runs.append(
            {
                "file": path.name,
                "when": start.get("ts", "?"),
                "task": start.get("task", "?"),
                "status": end.get("status", "running?"),
                "iterations": end.get("iterations"),
                "seconds": end.get("seconds"),
                "cost_usd": end.get("cost_usd"),
            }
        )
    return runs
