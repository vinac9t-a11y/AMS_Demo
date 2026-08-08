# Demo script — dry run 2026-08-07, 08:00 Eastern

One continuous beat, ~8 minutes. Presented from this machine, fully offline:
every artifact is a **real model run, recorded and replayed** (`REPLAYED_AI`),
which is hard rule 5 working as designed — say so proudly if asked.

## Before the call (5 minutes, do all of it)

```bash
demo/run_console.sh          # serves http://127.0.0.1:8700 — replay mode is the default
```

- Open http://127.0.0.1:8700 in a clean browser window. Close other tabs.
- `POST /api/reset` happens on the Reset button in the gate section — click it
  if the state is not pristine (all gates pending except G0).
- Keep one spare terminal tab with this pre-typed, as the CLI fallback:
  `LLM_MODE=replay LLM_PROVIDER=claude_cli .venv/bin/python demo/record_downstream.py`
- Have the backup video visible in Finder (see § Backup).

## The beat

| # | Do | Say |
|---|----|----|
| 1 | Land on **GATES** overview | "Five gates between intake and release. Nothing advances without passing one. Watch this strip — every step we take lights one of them." |
| 2 | Click **EPIC** on the rail | "Work enters as a business epic — this is the disability claim submission requirement, exactly as a business analyst wrote it. Open questions are carried, not invented." |
| 3 | Scroll to **ASSESS** | "The AI's first job is honesty: it fans the epic across delivery streams and classifies every task — agentic, AI-assisted, or manual. 59% of effort is agentic *in this run, measured, not claimed*. The system-of-record change is manual and externally owned — the AI flagged it and created a stub task so the other streams aren't blocked on it." |
| 4 | Scroll to **DESIGN** | "From the epic and assessment it produces the design — a data-flow diagram and entity model. Note the external boundary: every arrow into the system of record is a read. This is the deliverable the client named 'through design'." |
| 5 | **GATE** — type your name, click **Approve** | "First amber box. A person signs off the design, attributed by name. If I reject instead, story breakdown stays locked — the pipeline cannot run past a human who said no. (Tie back: that lit G1 on the strip.)" |
| 6 | **STORIES** | "Only after approval: three stories with testable acceptance criteria, decomposed into tasks. Every criterion is claimed by a task — that's gate G2, checked by the machine, not by a meeting." |
| 7 | **BUILD & RELEASE** — click **Run lane** | "Now the downstream. Three developer agents pick up the agentic tasks in parallel — like multiple developers. I'll walk through one; watch the feed: the Developer writes the page, the Tester writes tests against the acceptance criteria, pytest actually runs, and then — the part I want you to remember — an *independent* reviewer model, not the one that wrote the code, verifies it. No phase approves its own work." |
| 8 | Click **Run remaining lanes** | "The other agents complete the same way — I'm showing one in the interest of time. They merge at the integration point before integrated test. (Tie back: G3 just lit.)" |
| 9 | Show the **G3 review panel** | "This is the reviewer's actual verdict, criterion by criterion. In earlier runs it *rejected* builds — it caught a fabricated lookup fallback and disabled form validation, and the developer agent had to fix them before it would pass. The gate is adversarial, not decorative." |
| 10 | **G4** — type your name, **Approve release** | "Second amber box. A human approves the release; the server refuses this click unless the independent review passed." |
| 11 | Click **Open the application** | "And this is the delivered work: the plan-sponsor disability claim submission page — written by the developer agent in this run, tested, reviewed, released. Policy GRP-778120, member MBR-40917 —" *(do the lookup, fill a claim, attach a file, submit)* "— reference number, status Received." |
| 12 | Back to **GATES** overview | "All five gates green, every one earned on screen. That's the S7 claim: business requirement to production release, AI-assisted at every step, human control at both points that matter." |

## Questions to expect

- **"Is this live?"** — "It's a real model run, recorded and replayed — the
  same mechanism that makes it reproducible in your environment with zero
  keys. Recording once and replaying deterministically is a deliberate
  engineering rule, not a limitation." (Hard rule 5.)
- **"Are the estimates real?"** — "Placeholders today. The intent is to feed
  historical delivery data — past stories and actuals — and derive estimates
  from it."
- **"What about the manual tasks?"** — "They're first-class: routed to owning
  teams, labelled, and the effort-weighted coverage number counts them
  honestly. An articulated 59% beats a claimed 100%."
- **"Why is there a human gate at all?"** — "Progressive autonomy: approval
  starts on, and a workflow earns checkpoint removal by proving itself over
  many runs. The gate is where a workflow starts, not a permanent concession."

## Backup

Record the video **in isolation before the call** (Sita's instruction):
`⌘⇧5` → record window → run the beat once silently → save as
`~/Desktop/s7-demo-backup-2026-08-07.mov`. Keep it out of the repo.

## Fallback ladder (if something breaks live)

1. Refresh the page, click Reset — state is in-memory and self-heals.
2. Console dead → the spare terminal: run the CLI transcript, then open
   `artifacts/EPIC-S7-001/downstream/app/index.html` directly.
3. Machine trouble → play the backup video.
