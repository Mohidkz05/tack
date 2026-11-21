---
name: commit
description: Create small, focused git commits with Conventional Commit messages after checks pass. Use when the user asks to commit or when a unit of work is complete.
---

# Commit

1. **Check first.** `python3 .claude/hooks/tack verify --changed` must pass. Don't commit red.
2. **Look at what's staged:** `git status` and `git diff`. Never commit secrets, build output, or stray debug code.
3. **One logical change per commit.** If the diff mixes concerns (a refactor plus a feature), stage it in parts with `git add <paths>`.
4. **Write the message:**

   ```
   <type>(<optional scope>): <imperative summary, at most 72 chars>

   <why this change, not what. Wrap at 72 chars.>
   ```

   Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`. Add `!` after the type for breaking changes.
5. **Never** use `--no-verify`, amend pushed commits, or force-push shared branches unless the user explicitly asks.
