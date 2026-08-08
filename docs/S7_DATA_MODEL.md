# S7 Control Centre — Data Model

All factory models are Pydantic classes in `s7_delivery/factory/models.py`;
they round-trip through JSON under `artifacts/runs/<run-id>/` and through the
API. Ids are shared with the existing pipeline (EPIC-S7-001, US-xxx story
ids).

## Core hierarchy

```
Scenario ─ DeliveryRun ─ stages[5] ─ GateRecord[G0..G4]
Requirement → IntakeAnalysis → EpicRecord
EpicRecord → Story[7] → AcceptanceCriterion[]
Story → TaskRecord (work queue) → TestCaseRecord[] → ReviewReport
Quality report (checks/risks/exceptions) → release record → Deployment
                                                          → SupportHandover
```

## Story (the signed-plan unit)

`story_id, epic_id, title, purpose, accountable_team, contributing_teams,
owner, target_application, target_component, target_repository,
acceptance_criteria[], dependencies[], impacts[], feature_flag,
rollback_plan, task_type, estimate, sprint, status, risk, version,
traces_to[], provenance` — `completeness_gaps()` names anything missing and
feeds G1.

## Ledger records

- **ProvenanceRecord**: `event_id, artifact_id, artifact_type, version,
  sha256 (content hash), author, timestamp, inputs[], previous_version,
  run_id, stage, action, outcome`. Append-only. The `inputs` field is the
  dependency graph staleness detection walks.
- **ActivityEvent**: `timestamp, run_id, stage, actor, actor_type
  (human|service|simulation), workflow, skill, artifact, duration_s,
  outcome, details`. The reports page aggregates it.
- **Approval**: `approval_id, subject (plan|release), role, approver,
  decision, note, decided_at`.
- **Amendment**: reason, initiator, affected artifacts, impact assessment,
  required changes, implementation/verification/review status.

## Statuses

`not_started, ready, in_progress, waiting_for_input, waiting_for_approval,
blocked, failed, passed, completed, stale, invalidated` — used uniformly by
stages, tasks, checks and gates.

## Provenance labels

`human, live_ai, replayed_ai, staged, simulated`. The Control Centre's
engine-produced evidence is always `simulated` and badged in the UI.
