---
name: debug
description: Find and fix the root cause of a bug or failing check systematically instead of guessing. Use when something is broken, a test fails, or behavior is unexpected.
---

# Debug systematically

Guess-and-patch fixes the symptom and hides the bug. Find the cause first.

1. **Reproduce.** Get a command or test that shows the failure every time. If you can't reproduce it, gather more evidence before changing code.
2. **Capture it as a failing test**, when practical. It becomes your proof of the fix.
3. **Narrow it down.** Read the full error and stack trace. Bisect: inputs, recent commits (`git log -p`, `git bisect`), or by adding temporary logging at the boundaries.
4. **State the root cause** in one sentence before you fix anything: "X happens because Y."
5. **Fix the cause**, not the symptom. Check for the same pattern elsewhere in the code.
6. **Prove it.** The new test passes, the old tests pass, and `python3 .claude/hooks/tack verify --changed` is green.
7. **Clean up** temporary logging. Note the cause and fix in `PROGRESS.md` if it's worth remembering.

If you've tried three hypotheses without progress, stop. Summarize what you've ruled out and ask for input.
