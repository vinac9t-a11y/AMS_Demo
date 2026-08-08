# Overnight demo build — real recorded run, five-gate overview, downstream lane

**Date:** 2026-08-06, evening. **Deadline:** dry run tomorrow 08:00 Eastern,
presented from the local machine. **Approved:** verbally, this session.

## Why

Leadership did not buy the current demo: staged artifacts, stops at story
breakdown, governance-first pitch. Direction from tonight's team call:

1. Open with **one screen showing all five gates** end to end; every deep-dive
   ties back to it.
2. Downstream: **show one developer agent interactively; the other lanes
   complete at the click of a button**, then an integration point, then
   automated testing (one shown, rest asserted).
3. **Happy path only.** Manual/human-dependency scenarios are called out
   verbally, not built.
4. **Record a backup** and keep it handy in case of access failure.

Model access tonight is the Claude Code CLI (`claude -p`, headless). A Bedrock
token may come later; the provider seam makes that a config change.

## What gets built tonight

### 1. `claude_cli` provider in `common/llm.py`

A new provider that shells out to `claude -p --output-format json`. Uses the
existing login; no API key. Reports usage/cache counters from the CLI's JSON
result (blank when absent, per telemetry discipline). Record-time only: the
demo runs in `LLM_MODE=replay` from committed recordings, so nothing at demo
time depends on Claude Code existing. This keeps hard rule 4 intact.

### 2. Real recorded upstream

The existing stages (assessment → design/DFD → stories) get prompt functions
producing the same `models.py` shapes `staged.py` fakes today. Run once in
`LLM_MODE=record`; recordings land in `s7_delivery/cache/llm` and are
committed. Artifacts genuinely model-generated lose the `STAGED` badge; any
stage that fails to record cleanly stays staged **and stays badged**.

### 3. Thin downstream lane — one real task

For one `AGENTIC` task: Developer agent writes the code, Tester agent writes
pytest tests, tests actually run, Reviewer agent checks output against the
acceptance criteria. The Developer's artifact **is the demo app**: a
single-page MapleSure disability submission form (one HTML file + stdlib
server). Artifacts land at deterministic paths (the Sprint 2 artifact plane,
minimally). Lanes 2–3 are display-only parallel lanes that complete on click —
labelled as following the same recorded lane, not as live work.

### 4. Console: factory overview + agent activity

- **Overview screen:** the five-gate pipeline left to right, status lights,
  the opening shot and the screen every deep-dive returns to.
- **Agent activity pane:** which agent is working, on what, which artifact it
  wrote — rendered from telemetry/replay events, paced for legibility.
- **Downstream view:** three parallel developer lanes (one expanded), then
  integration point → test → release gate → Approve → "Open app" button.

### 5. Insurance

Recordings committed; then one clean run-through screen-recorded as the video
backup. Rehearse at least once end to end before stopping.

## The demo beat (tomorrow's script)

1. Factory overview — five gates, all pending.
2. Paste the EPIC → upstream agents run visibly → assessment (agentic/manual
   classification) → DFD → **Gate: sign-off — presenter clicks Approve**.
3. Stories unlock → downstream: lane 1 walked through (code → tests green),
   lanes 2–3 completed on click → integration → test → **release gate:
   Approve** → the MapleSure form opens in a browser tab.
4. Overview again: all gates green. "Everything you saw was a real model run,
   recorded and replayed — the same mechanism that makes it reproducible in
   your environment."

## Out of scope tonight

Sub-agents beyond Developer/Tester/Reviewer, multiple app screens, KPI panels,
negative paths, staleness detection, provenance ledger UI, sandbox
integration (weekend problem), Bedrock (config change when the token arrives).

## Honest-labelling rules carried forward

- A stage without a clean recording keeps its `STAGED` badge. No third option.
- Lanes 2–3 complete on click and are presented as "the same lane, run the
  same way" — not animated as if independently live.
- Telemetry logs what the CLI returns; blanks stay blank.

## Failure fallbacks, in order

1. Downstream recording fails → demo shows lane 1 only up to where it
   recorded; the rest stays staged and badged.
2. Upstream recording fails for a stage → that stage stays staged and badged;
   the run still traverses.
3. Console changes break → `demo/epic_to_stories_demo.py` CLI transcript plus
   the intake app as-is.
4. Everything on the day → the screen-recorded video.
