# Progress

> Shared memory between work sessions, for humans and agents. Update it before you stop.
> The tack session-start hook shows the end of this file to the agent automatically.

## Decisions

- 2026-11-21: Positioning is "enforcement-first". Big projects (Superpowers, Spec Kit, ECC) are mostly prompts; tack's edge is checks that actually run.
- 2026-11-21: No per-language project templates. New projects use each ecosystem's official generator through the `bootstrap` skill, so nothing goes stale.
- 2026-11-21: The CLI is Python using only the standard library. The runtime is one vendored file, so teammates and CI need nothing installed.
- 2026-11-21: `AGENTS.md` is the cross-agent rules file; `CLAUDE.md` imports it.
- 2026-11-21: Safe updates via `.tack/lock.json` hashes. Files the user edited are never overwritten without `--force`.

## Done

- 2026-11-21: Phase 1 core: detect (python/node/go/rust/java/Makefile, monorepos), verify, hooks (session-start memory, guard-bash, protect-files, format, stop-verify), `tack new` / `init` / `update` / `verify` / `detect`, 7 skills, 3 subagents, 82 tests. tack runs on itself.

## Current work

Phase 1 complete; waiting for the go-ahead on Phase 2 (see docs/PLAN.md).

## Next

1. `tack loop`: agent → verify → feed failures back, with run logs in `.tack/runs/`.
2. `tack doctor`.
3. GitHub templates: verify workflow and optional @claude bot.
4. CI for this repo (Linux, macOS, Windows), weekly self-update job, release workflow.
5. Full README with diagram and demo; Claude Code plugin packaging.
