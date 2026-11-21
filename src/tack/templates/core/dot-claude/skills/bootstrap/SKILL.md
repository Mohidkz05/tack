---
name: bootstrap
description: Turn a brand-new tack project (status "new" in tack.toml) into a working, verified skeleton. Interview the user, write SPEC.md, pick the stack, scaffold with official generators, and wire up tack.toml. Use right after `tack new`, or when the session-start note says the project is new.
---

# Bootstrap a new project

The goal is a small, real skeleton where every check runs and passes, before any feature work starts.

## 1. Interview (short)

Ask at most five questions, batched in one message:
- What are we building, and for whom? What does the first useful version do?
- Where does it run (web, CLI, mobile, API, library), and who maintains it?
- Hard constraints: a language you prefer or must use, hosting, budget, existing systems.
- What's explicitly out of scope for v1?

## 2. Write `SPEC.md`

Fill in the template: goal, users, v1 scope as a checklist, non-goals, constraints, and open questions. Show it and get a yes.

## 3. Propose a stack

Recommend **one** stack with a one-line reason, plus one alternative. Prefer boring, well-supported tools the user already knows. Wait for approval.

## 4. Scaffold with official generators

Use the ecosystem's own generator, run inside this repo, in non-interactive mode. Don't hand-write boilerplate a generator produces. Examples:

| Stack | Generator |
|---|---|
| Python | `uv init --package .`, then `uv add --dev ruff pytest mypy` |
| TypeScript web | `npm create vite@latest . -- --template react-ts`, plus eslint, prettier and vitest |
| Node API | `npm init -y`, plus typescript, tsx, vitest, eslint and prettier |
| Go | `go mod init <module>` |
| Rust | `cargo init` |
| Monorepo | one folder per component (e.g. `web/`, `api/`), each scaffolded on its own |

Every component needs a **formatter, linter, type checker (if the language has one), and a test runner**. Add one real smoke test per component.

## 5. Wire up the checks

```bash
python3 .claude/hooks/tack_runtime.py detect --write
python3 .claude/hooks/tack_runtime.py verify
```

`detect --write` fills in `tack.toml` and marks the project active. Open `tack.toml` and correct any command that's wrong for this setup. Iterate until verify passes.

## 6. Record and hand off

- Fill in the project description at the top of `AGENTS.md` (outside the tack block).
- Write `README.md`: what it is, how to run it, how to test it.
- Update `PROGRESS.md`: stack decisions with reasons, and the v1 checklist as next steps.
- Suggest a first commit: `chore: bootstrap <stack> skeleton`.
