---
name: build
description: Implement a change test-first (red, green, refactor) and finish only when tack verify passes. Use for any feature or behavior change once the approach is clear.
---

# Build test-first

## Loop

1. **Red.** Write the smallest test that captures the next piece of behavior. Run it and **watch it fail** for the right reason. A test that never failed proves nothing.
2. **Green.** Write the simplest code that makes it pass. No speculative extras.
3. **Refactor.** Clean up names, duplication, and structure while the tests stay green.
4. Repeat until the plan's "Proof" section is covered.

## Finish

1. Run the checks:

   ```bash
   python3 .claude/hooks/tack verify --changed
   ```

2. If something fails, read the output, fix the cause, and run it again. Never weaken a test or a lint rule to get green.
3. Show the final verify output in your reply. Don't summarize it as "all good".
4. Update `PROGRESS.md` with what changed and what's next.

## Hard-to-test code

If behavior truly can't be unit tested (UI feel, external services), say so explicitly. Test the logic around it, and describe the manual check you did.
