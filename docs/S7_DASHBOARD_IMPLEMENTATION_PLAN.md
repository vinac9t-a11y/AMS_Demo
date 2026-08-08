# S7 Delivery Control Centre — Implementation Plan

Created 2026-08-07. Status: **in progress** — updated at the end of each phase.

This plan adapts the "S7 Delivery Control Centre" specification to this
repository's ground rules. Two deliberate deviations from the spec as given,
both required by CLAUDE.md hard rules:

1. **Branding is MapleSure, not the client's.** Hard rule 2: no client names in
   code, data, commits, or UI. The visual theme follows the spec (white
   background, deep red primary accent, charcoal text, green/amber/red status
   colours) but every name, logo and label says MapleSure Insurance.
2. **The scenario is the existing disability epic, not "Claims Deductible
   Handling".** EPIC-S7-001 (online disability claim submission for plan
   sponsors) is what every committed replay recording, staged artifact and
   test in this repo is built against. The spec's deductible scenario would
   re-record the entire pipeline, which is blocked on LLM access. The spec's
   *structures* — 7-story decomposition, the deliberate boundary defect, the
   staleness sequence — are re-cast in the disability domain (decision
   confirmed by the user 2026-08-07).

The deliberate independent-review defect becomes a domain-correct boundary
error: the epic's business rule that a submission must be **rejected when the
absence duration is less than or equal to the plan's elimination period** is
first implemented with `<` instead of `<=`. AC-3's "equal to" case is missed;
independent review catches it; review result BLOCKED; correction; re-review
PASSED.

## 1. Current repository assessment

| Area | What exists | Reuse verdict |
|---|---|---|
| Pipeline contract | `s7_delivery/models.py` — frozen dataclasses: Epic, Assessment, AssessedTask, DesignArtifact, ReviewGate, UserStory, AcceptanceCriterion, Task (with `satisfies` traceability), Coverage, Provenance | **Reuse as-is.** The factory layer's Pydantic models reference these ids; no renames. |
| Orchestration | `s7_delivery/pipeline.py` — epic parse, staged/AI artifact selection, gate enforcement in `build_state` | **Reuse.** Control Centre reads the same pipeline for upstream stages. |
| Downstream lane | `s7_delivery/downstream.py` — developer/tester/reviewer roles, bounded revision loop, events.jsonl contract; recorded run in `artifacts/EPIC-S7-001/downstream/` | **Reuse recordings** as Replay-mode evidence; simulation mode generates equivalent deterministic events. |
| LLM abstraction | `common/llm.py` — 5 providers, replay/record/live, cache keyed on full prompt | **Reuse.** Factory simulation mode never calls it; Replay mode reads committed recordings through it. |
| Telemetry | `common/telemetry.py` | Reuse for any live calls; factory activity log is a separate JSONL (different concern: delivery events, not model calls). |
| Existing surfaces | `apps/console` (5-gate console), `apps/intake` (clarify→plan) | **Preserve untouched.** Control Centre is a third surface; no behaviour change to either. |
| Tests | 9 test modules, green offline | Preserve; add `tests/test_factory_*.py`. |
| Docs | demo script, sprint plan, architecture HTML pages | Extend; new docs listed in §8. |

## 2. Gaps the Control Centre fills

- No single overview composing intake → planning → build → quality → release.
- No persistent run state — console/intake state is in-memory per process.
- No provenance ledger with content hashes; `Provenance` is a label, not a chain.
- No staleness detection (upstream hash → downstream invalidation).
- No role model or per-role action gating.
- No amendment workflow / versioned artifacts.
- No quality-gate evidence aggregation.

## 3. Proposed architecture

```
apps/control/                  # third surface: the Control Centre
  server.py                    # FastAPI; thin HTTP over the factory engine
  static/index.html            # shell: header, left nav, stepper, pages
  static/styles.css            # MapleSure theme (white / deep red / charcoal)
  static/app.js                # renders entirely from /api/... JSON

s7_delivery/factory/           # the engine (no HTTP imports)
  __init__.py
  models.py                    # Pydantic: Run, Requirement, IntakeAnalysis,
                               #   Story, AC, TaskRecord, Team, ReviewReport,
                               #   QualityCheck, GateRecord, Approval, Risk,
                               #   Deployment, SupportHandover, Amendment,
                               #   ProvenanceRecord, ActivityEvent, StalenessResult
  store.py                     # artifact store: atomic JSON writes, append-only
                               #   JSONL, run directory layout (§19 of spec)
  seed.py                      # demo scenario seeded from EPIC-S7-001
  roles.py                     # role → permitted actions; enforced server-side
  gates.py                     # explicit gate conditions (never score-based)
  engine.py                    # run lifecycle, stage transitions, actions
  simulate.py                  # deterministic simulation of each stage's
                               #   evidence, incl. the deliberate <= defect
  staleness.py                 # upstream-hash pointers, invalidation walk
artifacts/runs/<run-id>/       # per-run artifact plane (gitignored except seed)
```

Rules live in the engine, not the UI: every gate check and role check is
server-side; frontend buttons reflect but never enforce.

**Provenance discipline carried over:** every artifact the Control Centre
shows carries a provenance label. Simulation-mode evidence is labelled
`simulated` (a new value alongside staged/replayed_ai/live_ai/human) and the
UI badges it — the spec's "customer-safe" must never become "provenance-free".

## 4. File-by-file change plan

New files only — no existing file is modified except `README.md`,
`.gitignore` (add `artifacts/runs/`), and docs. Existing apps untouched.

| File | Phase | Purpose |
|---|---|---|
| `s7_delivery/factory/models.py` | 1 | All factory Pydantic models |
| `s7_delivery/factory/store.py` | 1 | Atomic writes, JSONL ledgers, run dirs |
| `s7_delivery/factory/seed.py` | 1 | Scenario + 7-story decomposition |
| `s7_delivery/factory/roles.py` | 1 | Role permissions |
| `apps/control/server.py` | 1 | App shell + run CRUD endpoints |
| `apps/control/static/*` | 1 | Theme, nav, stepper |
| `s7_delivery/factory/engine.py` | 2 | Stage actions, gate checks |
| `s7_delivery/factory/gates.py` | 2 | Gate 0/1 conditions |
| `s7_delivery/factory/simulate.py` | 3 | Test-first + review simulation |
| `s7_delivery/factory/staleness.py` | 5 | Hash pointers, invalidation |
| `tests/test_factory_*.py` | 1–6 | Per-phase tests |
| `docs/S7_*.md` | 6 | Architecture, gates, demo script, etc. |
| `demo/run_control.sh` | 1 | One-command launch |

## 5. Development phases

Phase 1 Foundation → Phase 2 Intake+Planning → Phase 3 Build+Review →
Phase 4 Quality+Release → Phase 5 Governance → Phase 6 Hardening.
Each phase ends with green tests and a commit. The app runs after every phase.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Scope: the spec is weeks of work | Phased; app runnable after each phase; spec is the target, phases are the path |
| Confusing three surfaces | Control Centre is additive; console/intake untouched; README explains which surface demos what |
| Simulation mistaken for live AI | `simulated` provenance value, badged everywhere; Demo Mode selector visible in header |
| Invented metrics (confidence %, time saved) | Only computed-from-evidence numbers shown; no hardcoded "95% confidence" claims |
| State corruption on refresh/restart | All state on disk under `artifacts/runs/`; server is stateless between requests |

## 7. Test strategy

- Unit: gate conditions, role permissions, hash/staleness, provenance append,
  story completeness validation, atomic write behaviour.
- Integration: full happy-path run; review-block → correction → pass;
  upstream change → stale → blocked release → self-correction → clear.
- API: invalid transitions rejected, unauthorised approvals rejected,
  locked-plan edits rejected, reset restores seed.
- All offline, no API key, deterministic.

## 8. Run instructions (target)

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
demo/run_control.sh            # → http://127.0.0.1:8720
pytest tests/                  # all green offline
```

## Phase log

- 2026-08-07 — Phase 1: factory models, store (atomic + append-only),
  roles, engine lifecycle, seed, app shell. 26 tests.
- 2026-08-07 — Phase 2: intake + planning actions, explicit gates G0/G1,
  plan lock + contract artifacts, work-queue seeding. 14 tests.
- 2026-08-07 — Phase 3: test-first build simulation, isolated independent
  review, US-003 deliberate defect → block → correction → v2 pass. 12 tests.
- 2026-08-07 — Phase 4: quality evidence aggregation + G3, release
  approvals/rejection, Release-Manager-only deploy, handover. 13 tests.
- 2026-08-07 — Phase 5: ledger-derived staleness, SME-ruling upstream
  change, self-correction with versioned re-validation, amendments,
  traceability matrix. 15 tests.
- 2026-08-07 — Phase 6: scripted demo scenarios, reports view, API tests
  (15), docs (architecture, gates, data model, demo script, test strategy,
  security notes), README. Browser-verified end to end. **Complete** —
  195 tests green across the repo.
