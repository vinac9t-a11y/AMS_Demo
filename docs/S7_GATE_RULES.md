# S7 Control Centre — Gate Rules

A gate is its conditions. No gate is a score, and every unmet condition is
named with what is missing. All checks run server-side in
`s7_delivery/factory/gates.py`; the UI only displays the evaluated list.

## G0 — Intake complete

Passed by the Delivery Lead or Product Analyst when:
- a requirement is captured with a source document and named business owner,
- the intake analysis has run and names affected applications,
- the epic has been created,
- no unresolved critical blocker is raised.

Blocked otherwise, with the unmet conditions listed.

## G1 — Plan sign-off (Business Owner only)

- A plan exists (stories generated).
- Every story passes quality validation: purpose, testable acceptance
  criteria, one accountable team, target component, rollback plan, task type.
- Every dependency resolves inside the plan.
- A named approver signs.

On pass: the plan locks (`plan.json` + `plan.md` are the downstream
contract), the work queue is seeded in dependency order, and any further
change requires an amendment. Locked-plan edits are rejected server-side.

## G2 — Independent review

- At least one task completed; every completed task has a review.
- No review is blocked; zero unresolved major gaps.
- The reviewer is a separate role (`independent_reviewer`) that cannot run
  development actions — **no phase self-approves**.

The gate passes only when every task in the queue has completed with a
passing review.

## G3 — Quality (decided by the QA Lead)

Explicit conditions over the aggregated evidence:
- every requirement maps to a story; every acceptance criterion maps to
  code and to a test,
- required tests pass; coverage meets the threshold (80%, operational tasks
  excepted via a recorded exception),
- no unresolved critical security issue; no unresolved major review gap,
- no required artifact is stale,
- operational-readiness artifacts exist.

The quality score shown beside the table is informational only.

## G4 — Release (deploy decided by the Release Manager)

- All previous gates passed.
- Release approvals recorded by all four required roles — Business Owner,
  Engineering Lead, QA Lead, Release Manager — each under its own role, by a
  named person. A rejection blocks the gate and the release record.
- No stale artifacts.

Deploy is a distinct permission held only by the Release Manager. Approval
and decision are deliberately separate powers.
