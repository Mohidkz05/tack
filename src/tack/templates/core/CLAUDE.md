@AGENTS.md

## Claude Code specifics

- **Skills** (`.claude/skills/`): `plan`, `build`, `review`, `debug`, `commit`, `ship`, and `bootstrap` for brand-new projects. Use them; they encode how this repo expects work to be done.
- **Subagents** (`.claude/agents/`): send any non-trivial diff to `reviewer` before finishing; use `test-writer` for coverage gaps and `security-reviewer` for anything touching auth, input handling, secrets, or dependencies.
- **Hooks** (`.claude/settings.json`) block destructive commands and secret or lockfile edits, format files on save, and stop you from finishing while checks fail. If a hook blocks you, fix the cause. Never work around it.
