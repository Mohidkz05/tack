---
name: plan
description: Plan a non-trivial change before writing code. Use when a task touches more than one or two files, changes behavior users rely on, adds a dependency, or the right approach is unclear.
---

# Plan before you build

A plan is cheap; rework is expensive. The goal is a short, checkable plan the user can approve in under a minute.

## Steps

1. **Load context.** Read `SPEC.md`, `PROGRESS.md`, and the code you'll touch. Run the existing tests for that area so you know the baseline.
2. **Restate the goal** in one or two sentences, including what "done" looks like from the user's point of view.
3. **List unknowns.** Ask the user only about things you can't learn from the code. Batch the questions.
4. **Write the plan**, in this shape:

   ```markdown
   ## Goal
   <one or two sentences>

   ## Approach
   <the chosen approach, and in one line why it beats the obvious alternative>

   ## Changes
   - path/to/file: what changes
   - ...

   ## Proof
   - tests to add or change, and the command that shows they pass
   - any manual check

   ## Risks
   - what could break, and how we would notice
   ```

5. **Get approval** before making large or irreversible changes. Small, obviously safe steps can start right away.
6. **Save it.** Put the approved plan under "Current work" in `PROGRESS.md`, so a later session can continue it.

## Keep it small

If the plan has more than about 7 changes, split it into stages that each end with passing checks.
