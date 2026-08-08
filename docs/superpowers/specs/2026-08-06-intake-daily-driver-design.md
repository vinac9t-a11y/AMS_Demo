# Intake as a daily tool — artifact-plane persistence and full human review

**Date:** 2026-08-06
**Status:** approved design, pre-implementation
**Scope:** `apps/intake/` + `s7_delivery/intake.py` + new `s7_delivery/intake_store.py`

## Why

A roast of the current intake flow as a day-to-day workflow found three fatal
flaws: the approved plan lives only in server RAM and dies on restart; the
human can adjust metadata (lead, points, sprint) but cannot edit story *text*;
and the UI permits dependency-order violations the validator never checks.
This design removes all three and raises the app from demo beat to
daily-driver, staying inside the repo's hard rules (plain Python, files, no
external services).

It deliberately pulls the **artifact plane** (CLAUDE.md § Cache-efficient
agent architecture, decision 5 — scheduled Sprint 2) forward: intake becomes
its first producer, and the downstream lane its first consumer.

## 1 · Store — `s7_delivery/intake_store.py`

One module owns every path and every byte on disk. Nothing else writes.

```
artifacts/intake/<session-id>/
  session.json    # source of truth: epic, transcript, questions, plan,
                  # review log, approval, activity. schema_version field.
  review.jsonl    # append-only; one line per human decision (audit trail)
  plan.json       # written at approval: the contract-shaped plan the
                  # downstream lane consumes
  plan.md         # written at approval: stories + review trail + assumptions
                  # with answers + sign-off, human-readable
```

- `artifacts/` is gitignored runtime output.
- Session id: `<epic-id-slug>-<YYYYMMDD-HHMMSSZ>` fixed at creation.
- Writes are atomic (tmp file + `os.replace`). **Write-through ordering:
  disk first, then memory.** A failed write rejects the mutation (HTTP 500
  naming the path) and reloads state from disk.
- API: `save(session)`, `load(session_id)`, `list_sessions()` (directory
  scan, no cached index; unreadable dirs are skipped and reported),
  `append_review(session_id, entry)`, `export_plan(session)`.
- Round-trip: dataclasses ↔ JSON with explicit enum handling;
  `schema_version = 1` in every file; loader rejects unknown majors.

## 2 · Engine — `s7_delivery/intake.py`

All rules live here; endpoints stay thin. New/changed behaviour:

**Text editing (new).** `edit_story_text(session, story_id, field, value)`
for `title` and `narrative`; `edit_acceptance(session, story_id, ac_id,
text)` for criteria. Validation: non-empty after strip. Each edit lands in
the review log and marks the field in the story's `human_edited` set
(provenance honesty: AI draft, human-shaped, per field). Humans are not
forced into Given/When/Then — the log attributes their words to them.

**Dependency-order validation (new).** Sprint order = order of
`plan.sprints`. `move_story` rejects (ReviewError, naming the exact pair):
- moving a story into a sprint earlier than any of its `depends_on`;
- moving a story into a sprint later than any story that depends on it.

**Answer-an-assumption (new).** Assumptions get stable ids (`A1…` plan-level,
`S7-INT-3/A1` story-level). `answer_assumption(session, assumption_id,
answer)` records the answer (logged; immutable once absorbed).
`absorb_answers(session)` runs one `absorb-answers` LLM beat folding all
unabsorbed answers into the plan — validated by `_parse_plan` like every
other model output. **Does not consume the feedback-revision cap** (new
information is not a do-over). Absorb runs only when at least one unabsorbed
answer exists; a failed absorb keeps the answers recorded and retryable.

**Approve = second validator pass (changed).** `approve_plan` re-runs the
full integrity check before locking: dependency ordering across sprints,
every story in exactly one sprint, requirement coverage computed. Any
violation → ReviewError listing all of them. If unanswered assumptions
remain, approval requires `acknowledge_open_assumptions=True` and the log
records "signed with N open assumptions".

**Timestamps (changed).** `_now()` returns full ISO-8601 UTC
(`2026-08-06T08:38:23Z`). Session gains `updated_at`. The UI formats for
display.

**Per-sprint load (changed).** `DeliveryPlan.points_by_assignee_per_sprint()`
replaces plan-wide load as the UI's source. Overload flag applies per sprint.

**Lifecycle (changed).** Reset archives (session file remains; active
pointer clears). Draft sessions reopen for continued work; approved sessions
reopen read-only — every mutation path checks the lock after load, same as
before.

## 3 · Server — `apps/intake/server.py`

- Every existing mutation endpoint write-throughs via the store.
- New: `GET /api/sessions` (id, title, status, updated_at),
  `POST /api/sessions/{id}/open`, `POST /api/plan/edit-text`,
  `POST /api/plan/edit-acceptance`, `POST /api/assumptions/answer`,
  `POST /api/assumptions/absorb`. `POST /api/plan/approve` gains
  `acknowledge_open_assumptions: bool = False`.
- Payload adds: `session_id`, `updated_at`, `assumption_answers`,
  `artifact_paths` (approved only), `sessions` is its own endpoint.
- `ReviewError` → 400 (existing handler). Store write failure → 500.

## 4 · UI — `apps/intake/static/`

- **Home:** epic pane plus "Previous sessions" table (title, status badge,
  updated date; *continue draft* / *view approved*).
- **Clarify:** answers become auto-growing `<textarea>`s.
- **Draft plan:** one inline-edit pattern everywhere — pencil → field
  becomes input/textarea, Enter saves, Esc cancels; per-field
  "human-edited" chip. Assumptions panel splits open/answered, each open one
  takes an answer inline; "Fold answers into plan" button carries a
  pending-count badge. Team load renders per sprint (CSS bars, no chart
  lib).
- **Approve panel:** shows integrity-check status; when open assumptions
  exist, an acknowledgement checkbox must be ticked before the button
  enables. After approval: the three artifact paths, displayed.
- **Epic draft autosave** to localStorage (best-effort), cleared on
  successful intake.

## 5 · Errors

- Approve-time integrity failure → 400 listing every violation.
- Unreadable session file → 400 naming the path; the sessions list shows a
  warning row instead of the entry.
- Disk write failure → 500 naming the path; in-memory state reloaded from
  disk so screen and file never diverge.
- Absorb revision failing validation → error shown; answers retained.

## 6 · Testing (pytest, offline, `complete` patched)

- Store: save/load round-trip equality; atomic write leaves no tmp files;
  corrupt file skipped by `list_sessions` and surfaced.
- review.jsonl: append order matches review log.
- Dependency moves: blocked both directions with pair named; legal moves
  pass.
- Text edits: empty rejected; log + `human_edited` recorded.
- Assumptions: answer recorded; absorb consumes no feedback revision; absorb
  output faces `_parse_plan`; failed absorb keeps answers.
- Approval: integrity failure lists violations; open assumptions require
  acknowledgement; approved session stays locked across save/load.
- Export: `plan.json` parses to contract shape; `plan.md` contains stories,
  review trail, answered assumptions, sign-off.

## 7 · Docs

One-line updates in CLAUDE.md, AGENTS.md (kept in sync), and
`docs/SPRINT-PLAN.md` § Sprint 2: the intake half of the artifact plane
landed early; intake is its first producer.

## Out of scope (deliberate)

Jira/external export, authentication or multi-user, concurrent open
sessions, hand-editing streams/task-type/feature-flags, velocity-based
capacity, deleting sessions from the app.
