---
name: review
description: Review the current diff for bugs, risk, and quality before calling work done or opening a PR. Use after implementing a change, or when asked to review code.
---

# Review the diff

Review the change as if a stranger wrote it and you're responsible for it in production.

## Steps

1. Collect the diff: `git diff HEAD` (plus `git status` for new files).
2. For a non-trivial diff, also send it to the **`reviewer` subagent** for a fresh-context pass.
3. Go through the checklist. Report only real findings, most severe first, each with `file:line`, the problem, and a concrete failure scenario.

## Checklist

- **Correctness:** off-by-one errors, null or empty input, wrong conditions, unhandled errors, race conditions, wrong units.
- **Contract:** do callers still work? Public API, config, CLI flags, file formats, migrations.
- **Tests:** does a test fail if the change is reverted? Are edge cases covered?
- **Security:** untrusted input reaching shell, SQL, paths, or HTML; secrets in code or logs; new dependencies.
- **Simplicity:** dead code, duplication, needless abstraction, unclear names.
- **Scope:** changes unrelated to the task should be split out.

## Then

Fix confirmed issues, re-run `python3 .claude/hooks/tack verify --changed`, and list anything you deliberately left alone, with the reason.
