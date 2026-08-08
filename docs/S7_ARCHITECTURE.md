# S7 Delivery Control Centre — Architecture

The Control Centre is the third surface over this repo's delivery machinery,
beside the console (`apps/console`, port 8700) and the intake app
(`apps/intake`, port 8710). It demonstrates the full governed journey —
intake → planning → build & independent review → quality → release — as a
customer-safe browser application: no IDE, no terminal, no prompts, no
credentials, no raw logs on the surface.

## Layers

```
apps/control/server.py        HTTP translation only (FastAPI). No rules.
s7_delivery/factory/
  engine.py                   every action: role check → gate check → write
                              → provenance append → activity append
  gates.py                    explicit gate conditions (never a score)
  roles.py                    role → permitted actions
  simulate.py                 deterministic per-story evidence, incl. the
                              deliberate US-003 boundary defect
  staleness.py                stale = transitive input has a newer ledger record
  demo.py                     scripted scenarios driven through the engine
  store.py                    atomic JSON + append-only JSONL under
                              artifacts/runs/<run-id>/
  models.py                   Pydantic contracts for everything above
```

Rules live in the engine. The frontend (`apps/control/static/`) renders one
state payload (`GET /api/runs/<id>`) and reflects permissions; it never
enforces them — a disabled button is a hint, the 403/409 is the rule.

## State

All state is on disk under `artifacts/runs/<run-id>/` (gitignored). The
server holds nothing in memory, so a browser refresh or server restart loses
nothing. Current-state files are written atomically (tmp + `os.replace`);
ledgers (`provenance.jsonl`, `activity.jsonl`, `approvals.jsonl`,
`amendments.jsonl`) are append-only and never rewritten.

## Provenance and honesty

Every artifact carries a provenance label; the demo engine's evidence is
`SIMULATED` and badged as such everywhere it renders. This is the repo's
staged-output discipline (CLAUDE.md): nothing simulated may present as live.
The quality score is explicitly informational; every gate is a list of
named conditions with met/unmet detail.

## Staleness

The provenance ledger doubles as the dependency graph: each record names its
`inputs`. An artifact is stale when any transitive input has a record later
in the ledger than the artifact's own latest record. Detection re-runs on
every append, so an upstream amendment (DES-001 v2) marks the derived story,
change, tests, review and quality evidence stale immediately — and the
release gate blocks on the list. Correction always produces new versions;
nothing is silently updated.

## Relationship to the existing pipeline

`s7_delivery/pipeline.py` (the console's upstream stages) and
`s7_delivery/downstream.py` (the recorded three-role lane) are untouched.
The factory reuses their vocabulary — EPIC-S7-001, stories, acceptance
criteria, provenance labels — and the same FastAPI + vanilla-JS surface
pattern, so all three apps stay thin views over engines that own the rules.
