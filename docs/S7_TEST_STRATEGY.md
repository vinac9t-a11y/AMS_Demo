# S7 Control Centre — Test Strategy

All tests run offline, no API key, deterministic. `pytest tests/` runs the
whole repo; the factory's own modules are:

| Module | Covers |
|---|---|
| `tests/test_factory_store.py` | Atomic writes, append-only ledgers, path-escape rejection, content hashing, run-id sequencing |
| `tests/test_factory_engine.py` | Run lifecycle, state assembly from disk, reset-to-seed, role permission matrix, seed integrity (story completeness, dependency resolution, unique AC ids, defect target present) |
| `tests/test_factory_planning.py` | Intake ordering (analysis → epic → G0), planning behind G0, story edit versioning, editable-field allowlist, Business-Owner-only sign-off, plan lock rejecting edits, work-queue seeding |
| `tests/test_factory_build_review.py` | Dependency-ordered starts, red-baseline-before-develop, tests red→green with baseline preserved, reviewer/developer role isolation, the US-003 blocked review (major gap on AC3 while tests were green), correction cycle producing v2 and passing re-review, G2 pass on full queue |
| `tests/test_factory_quality_release.py` | Quality behind G2, checks computed from evidence, QA-Lead-only gate decision, release behind G3, deploy blocked until all four role approvals, rejection blocking, Release-Manager-only deploy, handover completing the run, approvals ledger |
| `tests/test_factory_staleness.py` | Detector unit behaviour (direct, transitive, cleared-by-new-version, unknown inputs), the full demo sequence: SME ruling → downstream stale → release blocked → self-correction versions every artifact → release proceeds; traceability chain completeness |
| `tests/test_control_api.py` | HTTP translation: 400 unknown role/mode, 403 forbidden role, 404 unknown run, 409 invalid transition and locked-plan edit, live-mode refusal, reset, all five demo scenarios producing their advertised states |

Conventions: engine tests drive the same public actions the API exposes —
there is no test-only backdoor. API tests monkeypatch `RUNS_ROOT` into a
temp dir, so no test touches `artifacts/runs/`.

Frontend is exercised by browser walkthrough (documented in the demo
script); the display layer holds no rules to unit-test — every button's
enforcement lives server-side and is covered above.
