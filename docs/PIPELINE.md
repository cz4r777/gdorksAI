# gdorksAI — Development Pipeline

The pipeline defines how a change moves from idea to merged code. Every change passes the same stages.

## Stages

```
┌──────────┐   ┌─────────┐   ┌────────┐   ┌──────────┐   ┌────────┐   ┌──────┐
│  Ticket  │──▶│ Design  │──▶│ Branch │──▶│ Implement│──▶│ Review │──▶│ Merge│
└──────────┘   └─────────┘   └────────┘   └──────────┘   └────────┘   └──────┘
                                                              │
                                                              ▼
                                                         ┌─────────┐
                                                         │  CI gate│
                                                         └─────────┘
```

### 1. Ticket
- All work starts as a GitHub Issue using a template (`bug`, `feature`, `dork-category`, `security`).
- Issue must state: problem, proposed change, acceptance criteria, scope (out-of-scope items listed explicitly).
- Labels applied: `phase:0|1|2|3|4`, `area:registry|ai|web|scope|docs|ci`, `priority:p0|p1|p2`.

### 2. Design (only for `feature` and `security`)
- Author writes a short design note inline in the issue (under ~30 lines). Trade-offs, alternatives considered, picked option.
- Supervisor signs off on the design before code.
- Bugs and dork-category PRs skip this stage.

### 3. Branch
- Branch naming: `<type>/<issue-number>-<short-slug>`. Examples:
  - `feature/12-dork-registry`
  - `bug/27-scope-guard-bypass`
  - `dork/41-add-supabase-category`
- Always branch from `main`. No long-lived feature branches.

### 4. Implement
- One ticket = one PR. Scope creep gets a follow-up ticket.
- Commit messages: imperative, ≤72 char subject, body explains *why*.
- Tests required for code touching `app/core/`. Optional for `app/templates/` and dork-data PRs.

### 5. CI gate
GitHub Actions runs on every push to PR branch:
- `ruff check .`
- `mypy app/core/`
- `pytest -q`
- Build the FastAPI app (import smoke test).

A red CI blocks review. No exceptions.

### 6. Review
- One human reviewer + supervisor sign-off.
- Review checklist (in PR template): scope-guard touched? secrets handled? AI prompts versioned? tests added?
- Security-labeled tickets need a second reviewer.

### 7. Merge
- Squash merge only. PR title becomes the squash-commit subject (keep it clean — it ends up in `git log`).
- Issue auto-closes via "Closes #N" in PR body.
- Update ROADMAP.md exit-criteria checkboxes if the PR moved the phase forward.

## Release pipeline
- Tag on `main` triggers a GitHub Release with auto-generated changelog from squash messages.
- v0.x.y until Phase 4 ships.

## Hot-fix path
- For p0 bugs (auth bypass, scope leak, secrets exposure): branch from `main`, fast-track review with two reviewers, no design stage. Still requires CI green.
