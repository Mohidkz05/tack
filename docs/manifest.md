# `tack.toml` reference

`tack.toml` is the project's **verification contract**: one file that tells every hook, agent, CI job and `tack loop` how to check the project, whatever the language. `tack init` (or `tack detect --write`) generates it; you own it afterwards.

```toml
[project]
name = "my-app"
status = "active"          # "new" until `bootstrap` scaffolds a stack
addons = ["ci"]            # managed by `tack add`

[hooks]
format_on_edit = true      # PostToolUse: format each edited file
on_stop = ["lint", "typecheck"]   # checks the Stop hook runs on changed components
timeout = 300              # seconds per command in hooks
require_progress = true    # Stop hook asks for PROGRESS.md notes after real work
progress_min_lines = 20    # ...when at least this many lines changed
routing = true             # playbook skill routing on prompts and edits

[guard]
protected = ["migrations/*"]           # extra paths agents may not edit (fnmatch globs)
deny_patterns = ['terraform\s+destroy'] # extra Bash regexes to block

[playbook]
source = "github:Mohidkz05/playbook"   # overrides the user-wide playbook for this project

[agent]
command = 'claude -p {prompt} --permission-mode acceptEdits --output-format json'
max_iters = 5              # default attempt limit for `tack loop`

[[components]]
name = "api"
path = "services/api"      # relative to the project root; "." for the root
stack = "python"
[components.commands]
setup = "uv sync"
format = "uv run ruff format ."
format_check = "uv run ruff format --check ."
format_file = "uv run ruff format -q {file}"
format_globs = "*.py,*.pyi"
lint = "uv run ruff check ."
typecheck = "uv run mypy ."
test = "uv run pytest -q"
build = "uv build"
```

## Checks

`verify` runs these checks, in order, for each selected component. A missing command is reported as `skip`, not as a failure.

| Key | Used by | Notes |
|---|---|---|
| `setup` | `verify --only setup`, CI | Install dependencies |
| `format_check` | the `format` check | **Never** mutates files. Must exit non-zero when formatting is off |
| `lint` | default verify, Stop hook | |
| `typecheck` | default verify, Stop hook | |
| `test` | default verify | |
| `build` | `verify --only build` | |
| `format` | `tack` users, agents | Mutating formatter for the whole component |
| `format_file` | PostToolUse hook | `{file}` is replaced with the edited file's quoted absolute path |
| `format_globs` | PostToolUse hook | Comma-separated filename globs that `format_file` applies to |

Commands run through the platform shell (`sh` / `cmd.exe`) with the component's `path` as the working directory, and they can use anything your shell can: `make test`, `./gradlew check`, `docker compose run --rm api pytest`.

The default `verify` set is `format, lint, typecheck, test`. Choose your own with `--only`.

## Selecting components

- `--component api,web` (or `-c`): by name
- `--changed`: only components containing files changed since `HEAD` (staged, unstaged, or untracked). The Stop hook always uses this.
- A file belongs to the **most specific** component whose `path` contains it, so `services/api` wins over `.` for `services/api/main.py`.

## Re-detecting

`tack update --detect` (or `python3 .claude/hooks/tack detect --write`) adds newly found components and fills in missing commands. **It never overwrites a command you've set.**

## Playbook

A playbook supplies stack picks and skill routes. tack looks for it in this order:

1. `[playbook].source` in this project's `tack.toml` (`tack playbook use <source> --project`)
2. `~/.config/tack/config.toml` (`tack playbook use <source>`), for every project on the machine

Sources can be `github:owner/repo` (or just `owner/repo`), any git URL, or a local folder. Remote playbooks are cloned to `~/.cache/tack/playbooks/` by `tack playbook sync`; hooks only read that local copy and never touch the network. See the [playbook repo](https://github.com/Mohidkz05/playbook) for the `routes.toml` format.

## Agents for `tack loop`

`[agent].command` is any CLI. `{prompt}` becomes one exact argument (the command runs without a shell). Without `{prompt}`, the prompt is sent on stdin. Examples:

```toml
command = 'claude -p {prompt} --permission-mode acceptEdits --output-format json'
command = 'codex exec {prompt}'
command = 'gemini -p {prompt}'
command = 'aider --yes --message {prompt}'
```

When the agent prints Claude Code-style JSON (`--output-format json`), tack records `total_cost_usd` per attempt. On a Claude subscription, this is an API-equivalent estimate, not a charge.
