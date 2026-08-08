# S7 Delivery — Sprint Plan

**AMS tabletop exercise · S7 (Full-Scale Application Development & Delivery)**
Demo insurer: MapleSure Insurance (fictional). Written 2026-08-03.
**Reordered 2026-08-04** after two design reviews — see § The reorder.

---

## The rule that shapes this plan

> **No sprint ends without a runnable demo beat.**

If a sprint cannot be shown at the end of it, it was scoped wrong. This is not a
presentation nicety — it is the scheduling mechanism. A sprint that can only be
described is a sprint whose risk is invisible until the week is gone.

Two consequences, applied throughout:

- **Every sprint below names its demo view explicitly.** That view is the exit
  criterion, not the code.
- **Sprints are ordered so the demo gets more honest, never more impressive.**
  The run ledger starts by saying "0 of 12 artifacts are AI-generated" and
  improves from there. At no point does the demo claim more than it has.

---

## The reorder — 2026-08-04

The plan previously ran foundation → surfaces → artifact plane → real AI →
downstream → enhancement lane. The downstream lane has moved up to second.

**Why.** S7's brief is *"business requirement through design, build, test and
production release"*, and the framing that came out of the design review was
**"S3 is partial, S7 is end to end"** — the S7 claim is coverage of every SDLC
deliverable. The console today stops at story breakdown, which is precisely
where it stops being distinguishable from what the enhancement lane already
does. Build, test, docs and release were the fourth thing to build and they are
half the named deliverable.

The downstream lane was already **decoupled from real LLM access by design**.
That decoupling was insurance; the reorder spends it. Everything routes through
`s7_delivery/models.py`, so the lane runs on staged artifacts and flips to real
output later without a line changing above the model layer.

**What this costs.** The stage-reuse beat and real AI output both move later,
and both were beats the plan liked. Neither is the claim S7 is assessed on.

| Was | Now | Sprint |
|---|---|---|
| Sprint 1 | **Sprint 1** | Surfaces, ledger, the `UserStory`/`Task` contract |
| Sprint 4 | **Sprint 2** | The downstream lane — build → test → docs → release |
| Sprint 2 | **Sprint 3** | Stage reuse and resume |
| Sprint 3 | **Sprint 4** | Real AI output and committed recordings |
| Sprint 5 | **Sprint 5** | Enhancement lane and the KPI scorecard |

---

## Naming — reconciled

The repo previously used *Sprint 0*, *Sprint A*, *Sprint B* and *Sprint 1* for
overlapping things. Unified on numbers as of 2026-08-03, then reordered
2026-08-04. Numbers always equal execution order; this table is the full history
so an older note can still be placed:

| Original | 2026-08-03 | Now | Meaning |
|---|---|---|---|
| Sprint 0 / Sprint A | Sprint 0 | **Sprint 0** | Foundation, staged artifacts |
| Sprint 1 | Sprint 1 | **Sprint 1** | Contract fixed; surfaces and ledger |
| — | Sprint 4 | **Sprint 2** | Downstream lane |
| — | Sprint 2 | **Sprint 3** | Artifact reuse and resume |
| Sprint B | Sprint 3 | **Sprint 4** | Real LLM calls + committed recordings |
| — | Sprint 5 | **Sprint 5** | Enhancement lane + scorecard |

---

## Dependency graph

```
Sprint 0  foundation ......................... DONE
          + prompt prefix ordering ........... DONE (reworked 2026-08-03)
          + cache telemetry .................. DONE
   │
Sprint 1  contract + surfaces + ledger
   │        UserStory / Task ......... DONE (settled 2026-08-04)
   │        artifact-plane contract
   │        verification as a stage
   │
Sprint 2  downstream lane: build → test → docs → release
   │                                   (NOT blocked by LLM access)
   │
Sprint 3  stage reuse + resume ......... droppable if the week tightens
   │
Sprint 4  real AI + recordings ......... (blocked: LLM access)
   │
Sprint 5  enhancement lane + KPI scorecard
```

Three ordering constraints are **hard**, not preferences:

1. **Prompt prefix ordering must precede any committed recording.** ✅
   **Discharged 2026-08-03** by the Sprint 0 rework. The cache key hashes the
   prompt by design, so restructuring prefixes after recordings exist
   invalidates every one of them. It is now a standing rule rather than a
   sequencing risk: **prefix order is frozen once Sprint 4 records anything.**
2. **The contract must precede the downstream.** `UserStory` and `Task` are the
   interface the downstream consumes; building it first means guessing at it.
   The reorder makes this constraint tighter, not looser — Sprint 1 now feeds
   Sprint 2 directly. The `Task` half was settled 2026-08-04.
3. **Anything the downstream will carry must be in the contract before Sprint 2
   builds it, not after.** This is the generalisation of constraint 1, and it is
   why two items moved *into* Sprint 1 below. Retrofitting a field through a
   lane that already exists means touching every stage in it.

---

## Sprint 0 — Foundation · **DONE** (reworked 2026-08-03)

**Goal.** A pipeline that runs end to end on staged artifacts, with the
determinism *and* cache-economics model correct before anything depends on them.

**Demo view.** The delivery console runs all five beats: epic intake →
assessment with effort-weighted coverage → DFD/ER diagrams → human review
gate → story breakdown. The gate genuinely blocks; rejection keeps stories
locked. Every artifact carries a visible `STAGED` badge.

**Built.** `common/llm.py` (5 providers, replay/record/live, loud replay
misses), `common/prompt.py`, `common/telemetry.py`, `s7_delivery/models.py`,
`pipeline.py`, `staged.py`, `apps/console/`, `crs/EPIC-S7-001.md`, **60 tests**
green offline with no API key.

### The rework — why it happened here rather than later

The cache-efficient architecture review (2026-08-03) produced two findings that
belong to the **foundation layer**: prompt assembly and cache telemetry both
live in `common/`. The sprint that originally carried the prompt work was the
wrong home for it.

The deciding fact: at the time of the rework the repo had **zero production LLM
callers and zero committed recordings**. Changing prompt assembly costs nothing
now and invalidates every recording later. This is hard ordering constraint 1
applied one sprint earlier than written, which is strictly cheaper.

**What changed.**

- **`common/prompt.py` (new).** `PromptLayers` assembles a prompt in fixed,
  stability-ordered layers — `rules → role → memory → ref → task` — splitting
  into `system = rules + role` and `prompt = memory + ref + task`. Providers
  cache a *prefix*, so a volatile segment placed early makes every stable
  segment after it a miss. Ordering by stability is the entire mechanism.
  It is plain string assembly; a provider that does no caching is unaffected.
- **`Usage` in `common/llm.py`.** The provider contract moved from
  `(text, int, int)` to `(text, Usage)`. Anthropic and Bedrock now report
  `cache_read_input_tokens` and `cache_creation_input_tokens`; the
  OpenAI-compatible providers leave them unset because they do not report them.
  This also removed a pre-existing `usage.prompt_tokens if usage else 0`, which
  fabricated a zero whenever a provider returned no usage object.
- **Cache counters in `common/telemetry.py`.** `log_call` carries them,
  `ScenarioSummary` aggregates them, and `cache_efficiency()` returns the
  read-to-write ratio — or `None`. It returns `None` when nothing reported
  counters, and `None` when writes are zero, because a ratio over zero writes is
  undefined rather than infinite.
- **Recordings persist cache counters**, so a replayed run reports the economics
  of the call that was actually made instead of collapsing to "not measured" —
  which matters because replay is the mode the demo runs in.

**The discipline, stated once.** Everywhere in this layer, an unreported number
stays `None` and never becomes `0`. **Zero is a measurement; `None` is an
admission.** A provider that cannot measure must not be presented as one that
measured a total miss. This is the same rule the existing code already applied
to cost, extended to cache.

**Known limitation.** Every artifact is still hand-written, not model output,
and labelled as such everywhere it appears. Streaming reports no cache counters:
providers surface them only on a final usage object that not every streaming
implementation exposes, so they stay unset there by choice.

---

## Sprint 1 — The contract, the surfaces, and the ledger

**Goal.** Freeze everything the downstream will consume, and produce one honest
number about the run.

This sprint grew on 2026-08-04. It now carries every decision that must be true
*before* Sprint 2 builds the lane, on hard ordering constraint 3 — each of them
is a field today and a refactor through five stages later.

**Demo view.** The same five beats, now runnable **two ways** — in the browser
and in the terminal — from the same pipeline. A persistent ledger strip reads:

```
Provenance   12 of 12 artifacts STAGED · 0 replayed-AI · 0 live
AI coverage  58% of estimated effort (3 tasks not AI-addressable)
Economics    Not measured — no live calls in this run
Mode         replay
```

The demo beat *is* the honesty. "Nothing here is AI-generated yet, and the tool
says so itself" is a stronger opening than a claim nobody can check.

**Builds.**

- ✅ **`Task`, the executable unit below `UserStory`** — **settled 2026-08-04.**
  The design review was explicit that the automated lane picks up *a task at a
  time*, split by technology, owning team and repository access. `UserStory`
  stays the planning artifact a human signs off; `Task` is what an agent is
  handed. `Task.satisfies` names the acceptance criteria it delivers, so
  traceability is a field rather than a paragraph; `UserStory.unsatisfied()`
  surfaces criteria no task claims. `Task.runs_in_downstream_lane` is the seam
  between the scopes — only `AGENTIC` tasks enter the lane, everything else is
  labelled as hand-work rather than quietly counted as coverage.
- **The artifact-plane contract** — deterministic paths, and a **provenance
  pointer at the upstream artifact each output derives from**, not just a
  provenance category. This makes the plane a chain that can be walked back to
  the request that caused it, and it is the answer to the review's context-loss
  objection: context survives a surface switch when the handoff is a validated
  file, not a conversation. *The contract only — the reuse behaviour is Sprint
  3.*
- **Verification as a stage.** The strongest idea from the second review was
  **no phase self-approves**: every artifact is checked by a separate verifier
  before the next stage may consume it, and the verdict is a field on the
  artifact. That has to exist in the contract before the lane is built. A
  "validate" button bolted on later is a feature; this is an invariant, and an
  invariant is what a governance story needs.
- `run_ledger()` in `pipeline.py` — one function, single source of truth
- `s7_delivery/cli.py` — `s7 epic` / `s7 run` / `s7 gate` / `s7 export`
- Web ledger strip + mode indicator, consuming the same function
- **Decision-level logging.** `common/telemetry.py` logs per *call*; the advice
  given most emphatically in the second review was to log every decision and
  why. The failure it prevents is real: people skip the logs and go straight to
  editing the prompt, which is guessing.

**Exit criteria.** Both surfaces render identical ledger figures. `UserStory`
and `Task` are frozen and documented. Tests cover the ledger through the CLI
(text is assertable; DOM is not).

**Blocked by.** Nothing. No LLM access required.

---

## Sprint 2 — The downstream lane

*Was Sprint 4. Moved up 2026-08-04 — this is the S7 claim.*

**Goal.** Close the loop from task to release, so the demo covers every SDLC
deliverable the brief names.

**Demo view.** Take one story from the breakdown, decompose it into tasks, and
carry an agentic one the rest of the way: generated code → failing tests (red) →
passing tests (green) → docs → release record. A **second gate** before release,
which blocks the same way the design gate does.

The narrative lands here: the app is where humans direct and review, the CLI is
where agents do the work, the two gates are where control sits — and a task that
is *not* AI-addressable visibly leaves the lane rather than being counted.

**Builds.**

- `build → test → docs → release` stages against the frozen `Task`
- **The bounded loop.** `write test → generate code → validate`, repeating until
  green, with a **hard iteration cap**. When the cap is hit the run **reports
  the remaining failures** rather than presenting partial output as success, and
  the validator triages each failure back to the stage that must fix it. The run
  record carries the verdict, per-phase results, the failure list, and open
  questions with ids — the `None`-is-an-admission discipline applied to a run.
- Release gate in the app; execution in the CLI
- Decide reuse-vs-rebuild of the sibling S3 downstream — **now** answerable,
  because the interface it consumes is fixed

**Exit criteria.** One task traverses the full lane. Both gates block. Stage
provenance is labelled throughout. A run that fails to converge says so.

**Blocked by.** Sprint 1 only. **Not** LLM access — every artifact in the lane
is staged, and labelled as staged, exactly like the upstream half.

---

## Sprint 3 — Stage reuse and resume

*Was Sprint 2. Moved down 2026-08-04. **Droppable** if the week tightens.*

**Goal.** Make stages independently re-runnable, and make the demo survive a
mid-run failure.

**Demo view.** Run the pipeline. Run it again — stages light up **REUSED**
rather than REGENERATED, because their output already exists and validates
against the contract. Then kill it mid-run and resume: it picks up where it
stopped instead of starting over.

This is a strong beat — it demonstrates determinism visually in one gesture, and
it is the demo-recovery mechanism. It is nonetheless the first thing to cut: it
makes the demo *safer*, not more complete, and the artifact-plane contract it
rests on already lands in Sprint 1.

**Builds.**

- `s7_delivery/artifacts.py` — reuse behaviour over the Sprint 1 contract
- Early-exit: valid output present → stage skips

**Exit criteria.** A second run of an unchanged epic performs no regeneration.
An interrupted run resumes.

**Blocked by.** Sprint 1 (the contract and the ledger that reports reuse).

---

## Sprint 4 — Real AI output and committed recordings

*Was Sprint 3. Moved down 2026-08-04 — it is the only externally blocked sprint,
so it no longer sits in front of work that is not blocked.*

**Goal.** Flip provenance from `STAGED` to `REPLAYED_AI`.

**Demo view.** The ledger changes on its own:

```
Provenance   3 of 12 artifacts STAGED · 9 replayed-AI · 0 live
Economics    $X.XX this run · cache reads N, writes M
```

And the proof that matters: **a fresh clone with zero API keys runs the whole
demo offline**, from committed recordings. That is the reliability claim made
checkable rather than asserted.

**Builds.**

- Swap `staged.py` for real `common.llm` calls, stage by stage
- Record and commit replay recordings to `s7_delivery/cache/llm`
- Wire cache read/write token counts into `telemetry.py` and the ledger

**Exit criteria.** Fresh clone, no `.env`, full run green. Economics reports
**our own measured numbers or nothing** — never zero, never an estimate, and
never a figure borrowed from any other team's benchmark.

**Blocked by.** ⚠️ **LLM access — an open external blocker.** Platform-team
approval is not settled. Interim options are an approved internal assistant, a
local model, or personal keys. If this never lands, the demo is still complete
end to end and honestly labelled — which is the entire point of the reorder.

---

## Sprint 5 — Enhancement lane and the KPI scorecard

**Goal.** Show both entry modes converging, and answer the metrics question.

**Demo view.** A mode selector on entry. **Project mode** starts at an epic and
runs the full upstream; **enhancement mode** starts at user stories and drops
straight into the downstream. Both converge on the same lane, shown side by
side. A scorecard reports the delivery KPIs the run can actually evidence.

**Builds.**

- Mode selector; S3-style enhancement lane
- Delivery KPI scorecard: velocity, cycle time, estimation accuracy, defect
  leakage, first-time-right, on-time/on-budget, cost per release

**Exit criteria.** Both lanes run. The scorecard shows measured values and
**blanks — not zeros — for anything a single run cannot evidence.**

⚠️ **Open, and it shapes this sprint:** whether the two lanes run on one
application or two. `CLAUDE.md` § Demo scenarios says two; the design review
assumes one, with the enhancement lane picking up a task from the S7 epic
itself. One application makes the "S7 decomposes, the enhancement lane executes"
stitch demonstrable rather than diagrammatic. Undecided — see § Open items.

---

## What is deliberately not in this plan

| Item | Why not |
|---|---|
| Agent role topology (a fixed specialist pool) | A candidate topology now exists from the second review, but mapping it onto S7's stages is not the constraint on any sprint below. Sprint 6+ |
| Persistent per-agent memory | Real value, but nothing in a one-week demo runs often enough to amortize it. Sprint 6+ |
| A skill registry / plugin layer | The coverage model already carries the client-facing half of this. Build the registry only if a second consumer appears |
| Third-party agent skills or marketplace packages | Untrusted instructions in an agent's context, and an external dependency the locked-down sandbox will not have |
| An IDE integration | Raised in the design review and left unresolved there. Nothing in this plan depends on the answer, and it is not ours to settle |
| A validation step that does not validate | If verification ships, it ships as a real stage (Sprint 1) or as a sentence in the deck. The middle option is the exact failure the staged-labelling rule exists to prevent |
| Any benchmark figure not measured by this repo | Non-negotiable. See risk R3 |

---

## Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | LLM access never approved | Sprint 4 cannot land; demo stays `STAGED` | **Substantially reduced by the reorder.** The full end-to-end lane no longer sits behind it. The staged labelling is honest and defensible on its own |
| R2 | Locked-down sandbox will not serve a port | Console unusable | The CLI from Sprint 1 is the fallback. Confirm with the platform team by email now, not in the room. Note the counter-pressure: the audience is upper management and they need something to *see*, so the console is the primary surface |
| R3 | A borrowed benchmark figure reaches a slide | Loses the room, and breaches another team's confidence | Only measured-here numbers ship. Empty states read "not measured", never `0` |
| R4 | One-week clock; staffing unsettled | Sprints 3–5 slip | Sprints are ordered so slipping the tail still leaves a *complete* demo rather than a truncated one — that is what moving the downstream lane to Sprint 2 buys. Sprint 3 is explicitly droppable |
| R5 | Prompt prefixes restructured after recordings land | Every recording silently invalidated | **Largely retired 2026-08-03**: the ordering landed in Sprint 0, before any recording existed. Residual risk is editing `common/prompt.py` after Sprint 4 — `test_prompt_layers.py` pins the order so the change cannot be silent |
| R6 | A field the downstream needs is discovered after Sprint 2 builds it | Refactor through every stage in the lane | Hard ordering constraint 3. The three known ones — `Task`, the provenance pointer, the verification verdict — are pulled into Sprint 1 for exactly this reason |

---

## Open items carried into the plan

- **One application or two?** See Sprint 5. The strongest argument for one is
  that it makes the stitch between the scopes demonstrable; the argument for two
  is that the console is built around the current scenario. Not decided.
- **Demo date and presentation format** — TBD. Sprint sizing is relative; the
  calendar is not yet set.
- **Staffing** — S7 needs more than one person; division of work unsettled.
- **Domain SME validation** — the disability submission scenario needs SME
  review of forms, required attachments, status names and pre-population rules.
- **LLM access** — see R1.
- **Browser availability in the locked-down environment** — see R2.
