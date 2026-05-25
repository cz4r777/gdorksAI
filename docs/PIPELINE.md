# gdorksAI — Development Pipeline

The pipeline defines how a change moves from idea to committed, pushed, reviewable code. The project now prefers immediate remote checkpoints over long-lived local-only branches and stacked merge holds.

## Stages

```
┌──────────┐   ┌─────────┐   ┌────────┐   ┌──────────┐   ┌────────┐   ┌────────────┐
│  Ticket  │──▶│ Design  │──▶│ Branch │──▶│ Implement│──▶│ Commit │──▶│ Push backup │
└──────────┘   └─────────┘   └────────┘   └──────────┘   └────────┘   └─────┬──────┘
                                                                             │
                                                                             ▼
                                                                       ┌─────────┐
                                                                       │CI / use │
                                                                       └────┬────┘
                                                                            ▼
                                                                       ┌────────┐
                                                                       │ Review │
                                                                       └────┬───┘
                                                                            ▼
                                                                       ┌──────┐
                                                                       │ Land  │
                                                                       └──────┘
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
- Branch from `main` when practical, but do not block progress on local base purity. Rebase later if needed.
- Long-lived hidden local branches are discouraged. If the work exists, it should usually be pushed.

### 4. Implement
- One ticket = one branch. A PR is optional until review or landing is needed.
- Commit messages: imperative, ≤72 char subject, body explains *why*.
- Tests required for code touching `app/core/`. Optional for `app/templates/` and dork-data PRs.

### 5. Commit + push checkpoint
- After each meaningful code update, commit and push the branch immediately unless the operator explicitly asks to hold it.
- The pushed branch is the backup / rollback checkpoint.
- Prefer smaller, reviewable commits over one giant local-only change.
- If a change is risky, push a known-good checkpoint before the next edit pass.

### 6. CI gate
GitHub Actions runs on every push:
- `ruff check .`
- `mypy app/core/`
- `pytest -q`
- Build the FastAPI app (import smoke test).

A red CI blocks landing and should trigger a fix pass, but it does not justify keeping code local-only.

### 7. Review
- Review can happen on a PR or on a pushed branch when the operator wants speed over ceremony.
- One human reviewer + supervisor sign-off is still preferred for substantial features.
- Review checklist (in PR template): scope-guard touched? secrets handled? AI prompts versioned? tests added?
- Security-labeled tickets need a second reviewer.

### 8. Land / merge
- If using a PR, squash merge is preferred.
- If the operator is working in a faster direct-push cycle, the pushed branch itself is the reviewable artifact and can be rebased or merged later.
- Issue auto-closes via "Closes #N" in PR body when a PR is used.
- Update ROADMAP.md exit-criteria checkboxes if the change moved the phase forward.

## Rollback model
- Incremental git history is the rollback mechanism.
- Every pushed commit is a recovery point.
- Prefer:
  - commit current good state
  - push
  - continue
- Avoid batching unrelated work into one irreversible lump.

## Release pipeline
- Tag on `main` triggers a GitHub Release with auto-generated changelog from squash messages.
- v0.x.y until Phase 4 ships.

## Hot-fix path
- For p0 bugs (auth bypass, scope leak, secrets exposure): branch from `main`, push immediately, fast-track review with two reviewers, no design stage. Still requires CI green before landing.
