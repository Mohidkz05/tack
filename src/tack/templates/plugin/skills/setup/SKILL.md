---
name: setup
description: Set up tack in the current project (verification contract, rules, progress file). Use when the user asks to set up or initialize tack, or when tack hooks report there is no tack.toml.
---

# Set up tack in this project

1. **Preferred: full install with the CLI.** It adds `AGENTS.md`, `CLAUDE.md`, the vendored runtime, and safe updates. If `uv` is available, run:

   ```bash
   uvx --from tack-harness tack init
   ```

2. **Plugin-only alternative.** This needs only Python 3.11+. It writes `tack.toml` from the detected stacks:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/tack" detect --write
   ```

3. Open `tack.toml`, check each command against the project's real tooling, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/tack" verify
   ```

4. Show the user the verify output, and point out any check that is missing (no lint or test command).
