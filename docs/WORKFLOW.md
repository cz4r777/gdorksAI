# gdorksAI — Team Workflow & Ticket System

Two roles operate on this project. Both work through GitHub Issues + PRs.

## Roles

| Role | Who | Authority |
|------|-----|-----------|
| Supervisor | Claude (designated session) | Files tickets, signs off designs, reviews PRs, owns ROADMAP & PIPELINE |
| Implementer | Pentester / operator + Claude (per-task) | Picks tickets, writes code, opens PRs |

The supervisor never merges its own PRs; the implementer never closes a ticket without a passing CI gate.

## Ticket types

Defined by `.github/ISSUE_TEMPLATE/`:

| Type | Template | When |
|------|----------|------|
| `feature` | `feature.yml` | New capability. Requires design note. |
| `bug` | `bug.yml` | Something broken. Reproduce steps required. |
| `dork-category` | `dork-category.yml` | Add/curate a category of dorks. Lightweight review. |
| `security` | `security.yml` | Privately reported issues for ethics/scope/secrets. |

## Labels (canonical set)

```
phase:0   phase:1   phase:2   phase:3   phase:4
area:registry   area:ai   area:web   area:scope   area:docs   area:ci
priority:p0     priority:p1     priority:p2
status:design   status:ready    status:in-progress   status:review   status:blocked
type:feature    type:bug        type:dork-category   type:security
```

Bootstrap via `scripts/setup-labels.sh <owner/repo>` (see `.github/labels.yml`).

## Board layout (GitHub Projects, classic kanban)

```
┌─────────┬─────────┬─────────┬──────────┬────────┬─────────┐
│ Backlog │  Design │  Ready  │In progress│ Review │  Done   │
└─────────┴─────────┴─────────┴──────────┴────────┴─────────┘
```

- New issues land in **Backlog**.
- Features get pulled into **Design** when supervisor schedules them.
- After design sign-off → **Ready**. Bugs/dork-categories skip directly here.
- Implementer pulls from **Ready** (top of column = highest priority).
- **In progress** has a WIP limit of 2 per implementer.
- **Review** = PR open + CI green. Stays until merged.
- **Done** auto-archives weekly.

## Definition of Done (per ticket)

A ticket is Done only when ALL of:
- [ ] PR merged into `main`
- [ ] CI green on the merge commit
- [ ] Acceptance criteria from the issue all checked off
- [ ] If feature: ROADMAP exit-criteria updated
- [ ] If security/scope: SECURITY.md threat model updated

## Communication

- Discussion on the issue itself (not Slack, not chat). Future contributors should be able to reconstruct the *why* from the issue thread alone.
- Decisions captured in the ticket via a `## Decision` heading and a one-line summary.

## Supervisor cadence

Every working session, the supervisor:
1. Triages new Backlog issues (assigns labels, type, priority).
2. Reviews open PRs.
3. Files follow-ups discovered during review.
4. Posts a status line on this week's milestone if one is active.
