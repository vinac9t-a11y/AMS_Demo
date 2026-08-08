# S7 Control Centre — 15-minute demo script

Setup (before the room): `demo/run_control.sh` → http://127.0.0.1:8720.
Everything runs offline, deterministic, no API key. If anything is mid-state
from rehearsal: **Settings → Reset this run**, or load a scenario fresh.

Roles are switched in the header ("Acting as"). Every approval asks for a
named person — use your own name; unattributed approvals are refused.

## Beat 1 — Intake to signed plan (4 min)

1. **Settings → New run.** Overview shows five stages, five gates, nothing
   asserted: every gate is a list of explicit conditions.
2. **Intake.** The requirement (human provenance) and its source document.
   Click *Run intake analysis* → affected applications, dependencies, risks,
   and the five open SME questions surfaced, not buried. *Create epic*,
   *Pass intake gate* — show the checklist that just evaluated.
3. **Planning.** *Generate draft plan* → 7 stories, one accountable team
   each, dependencies, sprints. Edit something inline (reassign a team,
   re-estimate) — note the version bump in Provenance later.
4. Switch role to **business owner**, sign off with your name. The plan
   locks: try an edit — the server refuses it. `plan.md` is now the
   downstream contract, and the work queue seeded itself in dependency
   order.

## Beat 2 — The defect the process catches (5 min)

*The strongest governance beat. Line to land: "green tests were not enough —
and the process knew."*

5. **Build & Review.** TASK-001: *Run to review* (each internal step logs:
   red baseline first, then implementation, then verification). Switch to
   **independent reviewer**, *Execute review* → passed. Repeat for TASK-002.
6. TASK-003 — *Run to review*. Point at the test-first table: every test
   failed initially, all green now. Then *Execute review* as the reviewer:
   **BLOCKED, one major gap.** Read FND-001 aloud: the criterion says
   *on or before*; the build (and its own test) implemented *before*. The
   reviewer verified against the criterion, not the tests.
7. *Return to development*, then as **engineering lead** rerun the cycle:
   the corrected build and corrected boundary test go green; re-review
   passes as v2. Nothing was overwritten — versions all the way down.
8. Finish the queue (TASK-004…007, *Run to review* + review each).
   G2 turns green only when the last review passes.

## Beat 3 — Quality, approvals, release (3 min)

9. **Quality.** *Run quality checks* — every row computed from the run:
   AC-to-code, AC-to-test, coverage vs threshold, review gaps. The score is
   labelled informational; as **QA lead**, *Decide quality gate*.
10. **Release.** *Request release approval*. Record all four approvals,
    switching roles each time (each is a named person under its own role).
    As **release manager**, *Deploy to production* → pipeline, smoke tests,
    post-checks. *Complete support handover* as **support lead** — run
    complete.

## Beat 4 — The upstream change (3 min)

*Load the prepared state instead of rebuilding: Settings → load
"Upstream change" scenario.*

11. **Risks & Alerts.** The SME ruling amended DES-001 (v2). Everything
    derived from it is stale — story, code, tests, review, quality evidence
    — each row saying why. **Release is blocked**; try Deploy to prove it.
12. *Run self-correction* — every stale artifact is re-validated as a new
    version, in order, on the ledger. Staleness clears; Deploy now passes.
13. Close on **Traceability** (pick US-003-AC3: requirement → design →
    story → criterion → task → change → tests → review → quality →
    deployment → handover) and **Provenance** (append-only, hashed,
    versioned). The pitch: *this is what governed AI delivery leaves
    behind — evidence, not claims.*

## Prepared scenarios (Settings → Load demo scenario)

| Scenario | Lands in |
|---|---|
| happy-path / full-run | Completed run, all gates green |
| review-failure | US-003 blocked, FND-001 on screen |
| missing-test-coverage | Quality gate blocked, QC-03 names the criterion |
| staleness | Approved, then upstream change; release blocked |
| release-rejected | Business Owner rejection on the record |

## If asked

- *"Is this live AI?"* — No. Every engine-produced artifact is badged
  SIMULATED; the run is deterministic on purpose (demo reliability rule).
  The pipeline behind the console (port 8700) shows recorded real model
  output; the architecture swaps the simulation for live calls behind the
  same interface.
- *"What stops the AI approving its own work?"* — Roles are server-side;
  the reviewer role cannot run development actions and vice versa. That is
  G2's standing condition, not a UI affordance.
