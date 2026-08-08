# AMS S7 Demo

**S7 — Full-Scale Application Development & Delivery.** A business-driven,
multi-sprint project taken end to end — business requirement → design → build →
test → production release — using an AI-assisted SDLC.

> **Status: Sprint 0 complete (reworked 2026-08-03).** The upstream pipeline
> runs end to end — epic intake → assessment → design → human review gate →
> story breakdown — and 60 tests pass offline with no API key.
>
> **Every artifact it renders is `STAGED`**: hand-written, not model output, and
> labelled as such wherever it appears. Real AI output is Sprint 3 and is blocked
> on model access. The downstream half (build → test → docs → release) is not
> built. See `docs/SPRINT-PLAN.md`.

## Where this sits

| | |
|---|---|
| **This repo** | S7 — the **delivery** scope |
| `../ams-s3-demo` | S3 — Minor Enhancement, the **support** scope |
| Elsewhere | S1, S2, S4, S5, S6 — built by the team, out of scope here |

This is a **new development**, not a fork of the S3 repo. Read S3 for patterns
worth borrowing; record the decision in `CLAUDE.md` before vendoring any of it.

## Read first

- **`CLAUDE.md`** — project context, hard rules, the decided flow, open questions.
- **`AGENTS.md`** — the same brief for Codex and other agents. Kept in sync with
  `CLAUDE.md` deliberately; change both together.

The demo insurer is the fictional **MapleSure Insurance**. The end client is
referred to only as "the client" — in code, data, commits, UI and docs alike.

## Setup

```bash
git clone https://github.com/AlanLands/ams-s7-demo.git && cd ams-s7-demo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # optional — not needed to run the staged demo
```

Python 3.12+. Dependencies are pinned, not ranged — the project has to survive a
port to a locked-down sandbox with no cloud services and no Docker.

`.env` needs no API key to run once replay recordings exist: `LLM_MODE=replay`
is the default and reproduces recorded outputs offline.

## Layout

```
s7_delivery/     the pipeline — epic intake, design/DFD, story breakdown,
                 then build/test/docs/release
  cache/         committed replay recordings (a deliverable — commit these)
  out/           per-run staging artifacts (gitignored, regenerated)
common/          shared clients — LLM, Jira, vector store. All LLM calls go
                 through common/llm.py; nothing else talks to a provider.
apps/            the target application(s) S7 delivers against, plus any console
crs/             requirement inputs — epics and change requests, scrubbed
data/            synthetic data only (gitignored except .gitkeep)
demo/            presenter scripts, reset scripts, rehearsal gates
docs/            design docs and generated artifacts
tests/           the pipeline's tests, and any target's regression suite
```

Two conventions carried from S3 that are worth keeping:

- **Regression suites live in `tests/`, outside every target root.** If a target
  root is ever scanned to build a codegen candidate pool, a test file sitting
  inside it joins that pool and the AI can rewrite its own invariant check.
- **`s7_delivery/cache/` is committed, `s7_delivery/out/` is not.** The first is
  what makes the demo deterministic; the second is per-run scratch.

## Running

Three surfaces, one machinery:

```bash
demo/run_console.sh          # → http://127.0.0.1:8700  five-gate console
demo/run_intake.sh           # → http://127.0.0.1:8710  epic intake (clarify → plan)
demo/run_control.sh          # → http://127.0.0.1:8720  S7 Delivery Control Centre
```

**The Control Centre** is the customer-safe, end-to-end governed journey:
intake → planning (Gate 1 locks the signed plan) → build & independent review
(test-first, a deliberate boundary defect caught by an isolated reviewer) →
quality (explicit gate conditions) → release (four named approvals, deploy,
support handover), with an append-only hashed provenance ledger, staleness
detection with self-correction, and full traceability. All engine-produced
evidence is deterministic simulation, badged `SIMULATED` — nothing simulated
presents as live. Docs: `docs/S7_ARCHITECTURE.md`, `docs/S7_GATE_RULES.md`,
`docs/S7_DEMO_SCRIPT.md` (the 15-minute walkthrough),
`docs/S7_DATA_MODEL.md`, `docs/S7_TEST_STRATEGY.md`,
`docs/S7_SECURITY_NOTES.md`.

No API key required — artifacts are staged, so it runs fully offline. The console
walks the five upstream stages; the review gate genuinely blocks, and rejecting it
keeps story breakdown locked.

The intended end state is a mode selector with two entry points converging on one
downstream lane. The right-hand lane and everything below the join are **not built
yet**:

```
Project mode (S7)                    Enhancement mode (S3-style)
  Epic → DFD/design → human review      User stories in
       → user stories ──────┬───────────────────┘
                            ↓
              build → test → docs → release      ← not built
```

### Documents

- `docs/SPRINT-PLAN.md` — the six sprints, each with its demo beat
- `docs/S7-Standalone-Plan.pdf` — plan for an offline single-file bundle
- `docs/delivery-pack.html` — the visual delivery pack; renders to PDF via
  `demo/render_pdf.py` once console screenshots are captured into `docs/assets/`
  (both are gitignored and not published)

See `CLAUDE.md` § The flow for why the design step sits before story breakdown,
and § Coverage model for how work that AI cannot do is surfaced rather than hidden.

## Validation

```bash
ruff check .
pytest tests/
```

## Hard rules

1. No real client data, ever — synthetic or public datasets only.
2. No client names in code, data, commits, or UI.
3. Secrets in `.env`, read from the environment. Never hardcoded, printed, or
   committed.
4. Must survive a port to a locked-down environment — plain Python, SQLite/CSV,
   pinned dependencies, no Docker-required path.
5. Demo reliability beats cleverness — rehearsed beats replay by default.

Full text and reasoning in `CLAUDE.md`.
