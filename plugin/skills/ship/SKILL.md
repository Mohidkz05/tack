---
name: ship
description: Get finished work ready to merge: full checks, review, progress notes, and a pull request. Use when a feature or fix is complete and the user wants to open a PR or release.
---

# Ship

1. **Run the full checks**, not just changed components:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/tack" verify
   ```

2. **Review:** use the `review` skill, plus the `reviewer` subagent for anything non-trivial.
3. **Update memory:** move the item to "Done" in `PROGRESS.md`. Update `SPEC.md` if the scope changed. Update the README or docs if behavior users see changed.
4. **Commit** using the `commit` skill.
5. **Open a PR** (ask before pushing). Use `gh pr create` with:
   - **What:** the change in two or three bullets.
   - **Why:** the motivation, linked to the issue or spec.
   - **Proof:** verify output, new tests, and manual checks.
   - **Risk:** what could break and how to roll back.
6. **Never** publish packages, deploy, or push tags without the user's explicit go-ahead.
