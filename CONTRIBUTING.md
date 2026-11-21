# Contributing to tack

Thanks for helping! tack is built with tack, so the workflow below is enforced by the repo's own hooks when you use Claude Code here.

## Setup

```bash
uv sync
uv run pytest          # all tests
uv run tack verify     # format, lint, test through tack's own contract
```

## Ground rules

- **The runtime stays stdlib-only.** `src/tack/runtime.py` is vendored into users' projects as `.claude/hooks/tack`; it must run on a bare Python 3.11 with no packages.
- **Templates are the source of truth.** After changing anything in `src/tack/templates/` or `runtime.py`:
  ```bash
  uv run tack update .              # refresh this repo's own .claude/ copy
  python3 scripts/build_plugin.py   # regenerate plugin/
  ```
  CI fails if either is out of sync.
- **Every bug fix comes with a test** that fails without the fix.
- **Cross-platform:** CI runs Linux, macOS and Windows. Don't assume `sh`, `/` paths, or UTF-8 consoles.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`...).

## Adding a stack

Add a detector function to `runtime.py` (see `_go` or `_rust` for small examples) that returns a commands dict, register it in `STACKS`, add the toolchain setup step in `install.CI_SETUP` / `ci_setup_steps`, and add tests in `tests/test_detect.py`.

## Adding an add-on

Create `src/tack/templates/addons/<name>/` with files as they should appear in a project (`dot-` becomes `.`, `.tmpl` files are rendered with `{{name}}`, `{{date}}`, `{{setup_steps}}`). It's available immediately via `tack add <name>`.
