# Changelog

## 0.1.1 (2026-11-21)

- Published on PyPI: `pip install tack-harness`.
- `tack add ci` / `claude-github` templates use the latest GitHub Actions majors (checkout v7, setup-python v7, setup-node v7, setup-go v7, setup-java v6, setup-uv v7, pnpm v6). A test now keeps the template versions in step with the repo's own Dependabot-managed workflows.
- Fixed: the plugin build script now reads and writes UTF-8 on Windows.

## 0.1.0 (2026-11-21)

First release.

- **Verification contract** (`tack.toml`): format / lint / typecheck / test per component; auto-detected for Python, Node/TypeScript, Go, Rust, Java/Kotlin and Makefiles, including polyglot monorepos and workspaces; parallel, `--changed`, JSON and Markdown output.
- **`tack new`** for new projects (the `bootstrap` skill scaffolds with official generators) and **`tack init`** for existing ones.
- **Hooks:** session memory (`PROGRESS.md`), command guard, protected secrets and lockfiles, format-on-edit, verify-before-stop.
- **7 skills and 3 subagents**; `AGENTS.md` for every agent, `CLAUDE.md` for Claude Code.
- **`tack loop`:** agent-agnostic run → verify → retry loop with JSONL run logs and cost tracking; `tack runs`.
- **`tack doctor`**, **`tack update`** (hash-tracked, never clobbers edits), **`tack add ci | claude-github`**.
- **Claude Code plugin** and marketplace.
- Self-maintenance: weekly Claude Code release watch, Dependabot, CI on Linux/macOS/Windows.
