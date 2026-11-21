# Progress

> Shared memory between work sessions, for humans and agents. Update it before you stop.
> The tack session-start hook shows the end of this file to the agent automatically.

## Decisions

- 2026-11-21: Positioning is "enforcement-first". Big projects (Superpowers, Spec Kit, ECC) are mostly prompts; tack's edge is checks that actually run.
- 2026-11-21: No per-language project templates. New projects use each ecosystem's official generator through the `bootstrap` skill, so nothing goes stale.
- 2026-11-21: The CLI is Python using only the standard library. The runtime is one vendored file, so teammates and CI need nothing installed.
- 2026-11-21: `AGENTS.md` is the cross-agent rules file; `CLAUDE.md` imports it.
- 2026-11-21: Vendored runtime has no .py extension, so project linters, formatters and test runners never touch it.
- 2026-11-21: Safe updates via `.tack/lock.json` hashes. Files the user edited are never overwritten without `--force`.

## Done

- 2026-11-21: Phase 1 core: detect (python/node/go/rust/java/Makefile, monorepos), verify, hooks (session-start memory, guard-bash, protect-files, format, stop-verify), `tack new` / `init` / `update` / `verify` / `detect`, 7 skills, 3 subagents, 82 tests. tack runs on itself.

- 2026-11-21: Phase 2 automation: `tack loop` (any agent CLI, retries with failure output, timeout-safe, JSONL run logs with cost), `tack runs`, `tack doctor`, `tack add ci|claude-github`, `verify --markdown`. 102 tests.
- 2026-11-21: First real `tack loop` run with Claude (subscription): fixed a buggy slugify in 1 attempt, 40s. The run exposed 3 bugs, all fixed: the project's linter checked tack's vendored .py file (renamed to extension-less `.claude/hooks/tack`), cost parsing broke on leading warnings, and a no-change attempt counted as a pass.

## Current work

Phase 3: polish and publish (see docs/PLAN.md).

## Next

1. CI for this repo (Linux, macOS, Windows, Python 3.11-3.13) plus a vendored-runtime sync check.
2. Weekly self-update job and Dependabot for GitHub Actions; release workflow.
3. Full README with diagram and demo; docs/manifest.md (linked from the tack.toml header).
4. Claude Code plugin packaging.
5. Put the real demo transcript in the README.
