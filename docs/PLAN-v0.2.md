# Plan: tack v0.2 + playbook

**One line:** a separate **playbook** holds your picks (stacks, skills, plugins) and keeps itself current. **tack** makes Claude actually use them, and makes sure progress always gets saved.

Status: done, released as tack v0.2.0 + playbook (2026-11-21).

---

## Part A: playbook (new repo, `Mohidkz05/playbook`)

The content: your opinions, written down once, used by every project.

```
playbook/
├── stacks/               # what to build with, per project type
│   ├── web-app.md        # framework, styling, tests, deploy, plus the setup command
│   ├── api.md
│   ├── cli.md
│   ├── mobile.md
│   ├── ai-app.md
│   └── library.md
├── routes.toml           # "in this situation → use this skill/plugin"
├── skills.md             # recommended skills and plugins, what each is for, how to install
└── .github/workflows/
    └── research.yml      # weekly: research new tools and skills, open a PR with updates
```

**What a route looks like:**

```toml
[[route]]
name = "ui"
skill = "impeccable"
reason = "Any substantial UI work: new screens, redesigns, polish"
files = ["*.tsx", "*.jsx", "*.vue", "*.svelte", "*.css", "*.html"]
words = ["ui", "design", "layout", "page", "component", "style"]
```

- [x] **A1. Stack picks.** Researched with current sources (not from memory). For each project type: the recommended stack, one line on why, and the official setup command.
- [x] **A2. Routes.** Start from your existing `CLAUDE.md` design table and expand it to testing, APIs, databases, AI/LLM work, deploy, security, and docs.
- [x] **A3. Skills catalog.** Every skill and plugin the routes mention, with install commands, including the ones you already have.
- [x] **A4. Weekly research job.** Claude checks for new framework versions and popular new skills and plugins, then opens a PR you approve. Without an API key, it opens an issue checklist instead.
- [x] **A5. Checks.** Tests that every route is valid and every stack file has the required sections.

## Part B: tack v0.2 (the engine)

- [x] **B1. Progress is always saved.** When Claude tries to finish: if code changed but `PROGRESS.md` didn't, Claude is sent back once to update it. Tiny changes don't trigger it. You can turn it off in `tack.toml`.
- [x] **B2. Connect a playbook.** Set it once for your whole computer:
  ```
  tack playbook use github:Mohidkz05/playbook
  ```
  Every project then uses it. One project can use a different playbook. `tack playbook sync` pulls the latest version.
- [x] **B3. Automatic skill routing.** A hook that watches what's happening:
  - You mention UI, or Claude starts editing a `.tsx` file → Claude is told "this is UI work: use `impeccable`".
  - It tells Claude only **once per session** per route, so it doesn't nag.
- [x] **B4. Stack picks in new projects.** `bootstrap` reads the playbook's `stacks/`, so `tack new` projects start with your standard choices. Claude still asks before using them.
- [x] **B5. Doctor checks the playbook.** It warns when a route points to a skill or plugin you haven't installed, and shows how to install it.
- [x] **B6. Tests, docs, and release** as v0.2.0 on GitHub and PyPI.

## Order

1. **B1** (progress saving): small and independent, ships first.
2. **A1-A3** (playbook content): research and write.
3. **B2-B5** (tack uses the playbook).
4. **A4** (weekly research job), then **B6** (release).

## Later

- Share playbooks: anyone can point tack at their own.
- Routing for more tools (Cursor rules, Codex).
- Routes that learn: notice which skills actually helped, and suggest changes to routes.

## Done means

- In a fresh project, saying "make the landing page look better" makes Claude load `impeccable` without being told.
- `tack new` suggests your standard stack from the playbook.
- Ending a session after code changes always leaves `PROGRESS.md` updated.
- The playbook opens its own weekly update PR.
