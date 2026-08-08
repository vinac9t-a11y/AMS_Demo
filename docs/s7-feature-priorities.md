# S7 feature priorities — working backlog

Ten prioritized capabilities captured from an internal email (2026-08-06).
Source identifiers scrubbed per hard rule 2 — no client or company names, and
source-specific acronyms replaced with neutral terms. The plan is to develop
these point by point; each section carries a status line mapping it to what
this repo already has.

| # | Feature | Description | Score |
|---|---------|-------------|-------|
| 1 | Gated Pipeline (5 gates) | Hard phase gates from intake through release; no advancement without required artifacts and gate conditions. | 10 |
| 2 | Four-Layer Architecture | Separates rules, skills, workflows, and orchestrator so AI delivery operates as a governed engineering system. | 10 |
| 3 | Story Quality Standards | Requires clear purpose, testable acceptance criteria, dependencies, target component, impacts, feature flag, rollback plan, and task type. | 9 |
| 4 | Provenance Ledger | Append-only SHA-256 tracking of artifact versions, authors, timestamps, and input dependencies for auditability. | 9 |
| 5 | Factory Activity Log | Logs AI-assisted sessions, workflows, skills, artifacts, duration, and outcomes to reveal velocity and bottlenecks. | 9 |
| 6 | Independent Review Protocol (Gate 3) | Three-layer review process. Uses an isolated reviewer to verify acceptance criteria against design and code; critical or major gaps block release. | 8 |
| 7 | Traceability Matrix | Links epic, design doc, story, PR, test, and deployment so defects can be traced backward quickly. | 8 |
| 8 | Self-Correction / Change Management | Manages rule, skill, workflow, and orchestrator changes through impact assessment, implementation, stability verification, and versioned amendments. | 8 |
| 9 | Gates 0–2 (Completeness Checks) | Enforces requirement-to-story mapping, testable acceptance criteria, and full AC-to-code/test coverage before review. | 8 |
| 10 | Staleness Detection | Marks downstream stories or code stale when upstream design or stories change, forcing updates before release. | 7 |

---

## 1 · Gated Pipeline (5 gates) — score 10

Hard phase gates from intake through release; no advancement without required
artifacts and gate conditions.

- **Status:** partially built. One human review gate exists (design → stories)
  and genuinely blocks. The release gate is planned as Sprint 2's "second
  gate". This item generalises both into a five-gate model spanning the whole
  pipeline.
- **Development notes:** _TBD_

## 2 · Four-Layer Architecture — score 10

Separates rules, skills, workflows, and orchestrator so AI delivery operates
as a governed engineering system.

- **Status:** partially built. Maps closely onto the existing
  `rules → role → memory → ref → task` prompt-prefix convention in
  `common/prompt.py` and the pipeline orchestration in
  `s7_delivery/pipeline.py`. The framing here is architectural (a layer
  diagram), not just prompt ordering.
- **Development notes:** _TBD_

## 3 · Story Quality Standards — score 9

Requires clear purpose, testable acceptance criteria, dependencies, target
component, impacts, feature flag, rollback plan, and task type.

- **Status:** contract work — belongs in `s7_delivery/models.py` alongside the
  Sprint 1 `UserStory`/`Task` freeze. Several fields (feature flag, rollback
  plan, impacts) are not in the current shape. Anything the downstream carries
  must land before Sprint 2 builds the lane.
- **Development notes:** _TBD_

## 4 · Provenance Ledger — score 9

Append-only SHA-256 tracking of artifact versions, authors, timestamps, and
input dependencies for auditability.

- **Status:** partially designed. `models.py` carries `Provenance`, and the
  Sprint 2 artifact plane already plans upstream-artifact pointers. New parts:
  append-only ledger semantics and content hashing.
- **Development notes:** _TBD_

## 5 · Factory Activity Log — score 9

Logs AI-assisted sessions, workflows, skills, artifacts, duration, and
outcomes to reveal velocity and bottlenecks.

- **Status:** partially built. `common/telemetry.py` logs per call; Sprint 1's
  run ledger is the client-facing face. This adds session/workflow-level
  aggregation and the velocity/bottleneck view — aligns with the existing note
  that decision-level records are missing.
- **Development notes:** _TBD_

## 6 · Independent Review Protocol (Gate 3) — score 8

Three-layer review process using an isolated reviewer to verify acceptance
criteria against design and code; critical or major gaps block release.

- **Status:** concept-only per design review 2026-08-04 item 4 ("independent
  model review"). If shown without executing live, it ships badged `STAGED` —
  no third option. The "no phase self-approves" invariant from the second
  review is the structural version of this.
- **Development notes:** _TBD_

## 7 · Traceability Matrix — score 8

Links epic, design doc, story, PR, test, and deployment so defects can be
traced backward quickly.

- **Status:** partially designed. `Task.satisfies` already carries
  acceptance-criterion ids; the second review's `traces_to` pattern extends
  this to a full chain. The matrix is the rendered view over that chain.
- **Development notes:** _TBD_

## 8 · Self-Correction / Change Management — score 8

Manages rule, skill, workflow, and orchestrator changes through impact
assessment, implementation, stability verification, and versioned amendments.

- **Status:** not built. Governance for changing the delivery system itself
  (the layers in item 2), not the product. Likely a documented process +
  version-controlled rule files rather than code, at demo scale.
- **Development notes:** _TBD_

## 9 · Gates 0–2 (Completeness Checks) — score 8

Enforces requirement-to-story mapping, testable acceptance criteria, and full
AC-to-code/test coverage before review.

- **Status:** not built. These are the machine-checkable gates upstream of the
  human/independent review — `UserStory.unsatisfied()` is the seed of the
  AC-coverage check.
- **Development notes:** _TBD_

## 10 · Staleness Detection — score 7

Marks downstream stories or code stale when upstream design or stories change,
forcing updates before release.

- **Status:** not built. Composes with the artifact plane: if artifacts carry
  upstream pointers and content hashes (item 4), staleness is a hash mismatch
  along the chain. Natural Sprint 2+ follow-on.
- **Development notes:** _TBD_
