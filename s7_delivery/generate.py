"""Real model-generated upstream artifacts — the same shapes `staged.py` fakes.

Selected by `S7_ARTIFACTS=ai` (see `pipeline.build_state`). Every call goes
through `common.llm.complete`, so `LLM_MODE=record` records against the live
provider and `LLM_MODE=replay` replays the committed recordings offline.

Provenance is `REPLAYED_AI` in replay mode and `LIVE_AI` otherwise — never
`STAGED`, because this module only returns output a model actually produced.
A failure here (replay miss, malformed JSON, invalid diagram) raises; the
caller falls back to `staged`, which keeps its badge. No third option.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from common.llm import complete
from s7_delivery.models import (
    AcceptanceCriterion,
    AssessedTask,
    Assessment,
    Coverage,
    DesignArtifact,
    Epic,
    Provenance,
    Stream,
    Task,
    UserStory,
)

_SYSTEM = (
    "You are a delivery analyst in MapleSure Insurance's AI-assisted SDLC "
    "pipeline. MapleSure is a fictional insurer in a tabletop exercise. "
    "Output strict JSON matching the schema given in the task — no prose, no "
    "markdown fences. Ground every statement in the epic text you are given; "
    "where the epic lists open questions, downstream artifacts carry them as "
    "assumptions rather than invented answers."
)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _provenance() -> Provenance:
    mode = os.environ.get("LLM_MODE", "replay").lower()
    return Provenance.REPLAYED_AI if mode == "replay" else Provenance.LIVE_AI


def parse_json_block(text: str):
    """Parse a JSON reply, tolerating a model that wrapped it in a fence."""
    text = text.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


# --- assessment ------------------------------------------------------------


def assessment(epic: Epic) -> Assessment:
    streams = ", ".join(s.value for s in Stream)
    prompt = f"""Here is a business epic:

---
{epic.body}
---

Produce the initial delivery assessment: break the epic into 6 to 9 tasks
routed across delivery streams. Allowed stream values: {streams}.

Classify each task's coverage honestly:
- "agentic"              — runs end to end in the automated delivery lane
- "ai_assisted_external" — AI drafts it, but another team owns the change
- "manual"               — human work, no AI contribution claimed

The epic itself flags a system-of-record change that is externally owned and
manual on this timeline — reflect that: at least one task must be manual or
ai_assisted_external with blocked_by_external true, and tasks that wait on it
name it in depends_on. Estimates are in days and should differ by task size.

JSON schema:
{{"tasks": [{{"id": "T1", "summary": str, "stream": str, "coverage": str,
"estimate_days": float, "rationale": str, "depends_on": [str],
"blocked_by_external": bool}}],
"integration_note": str}}

integration_note names where parallel streams merge before integrated test."""
    data = parse_json_block(
        complete(prompt, system=_SYSTEM, json_mode=True, cache_key="s7:assess")
    )
    tasks = tuple(
        AssessedTask(
            id=str(t["id"]),
            summary=str(t["summary"]),
            stream=Stream(t["stream"]),
            coverage=Coverage(t["coverage"]),
            estimate_days=float(t["estimate_days"]),
            rationale=str(t.get("rationale", "")),
            depends_on=tuple(str(d) for d in t.get("depends_on", [])),
            blocked_by_external=bool(t.get("blocked_by_external", False)),
        )
        for t in data["tasks"]
    )
    return Assessment(
        epic_id=epic.id,
        tasks=tasks,
        integration_note=str(data.get("integration_note", "")),
        provenance=_provenance(),
        generated_at=datetime.now(UTC),
    )


# --- design ----------------------------------------------------------------


def design(epic: Epic, assessment: Assessment) -> tuple[DesignArtifact, ...]:
    task_lines = "\n".join(
        f"- {t.id} [{t.stream.value}/{t.coverage.value}] {t.summary}" for t in assessment.tasks
    )
    prompt = f"""Here is a business epic:

---
{epic.body}
---

The delivery assessment routed it into these tasks:
{task_lines}

Produce two design diagrams in Mermaid source for the target-state online
disability claim submission journey in SponsorConnect:

1. A data flow diagram: sponsor → portal → services → policy/member system of
   record lookup (read-only, externally owned) → document store → handoff to
   the existing intake/indexing path. Mermaid `flowchart LR`.
2. A relationship diagram of the core entities (plan sponsor, member, policy,
   submission, document, status). Mermaid `erDiagram`.

Keep each diagram under 25 lines, well-labelled, renderable by mermaid v10.
JSON schema:
{{"dfd": {{"title": str, "mermaid": str, "notes": str}},
"er": {{"title": str, "mermaid": str, "notes": str}}}}

The mermaid value for dfd must start with "flowchart"; er must start with
"erDiagram". notes is 2-3 sentences a reviewer reads before approving."""
    data = parse_json_block(
        complete(prompt, system=_SYSTEM, json_mode=True, cache_key="s7:design")
    )
    dfd = data["dfd"]
    er = data["er"]
    if not str(dfd["mermaid"]).lstrip().startswith("flowchart"):
        raise ValueError("DFD mermaid source does not start with 'flowchart'")
    if not str(er["mermaid"]).lstrip().startswith("erDiagram"):
        raise ValueError("ER mermaid source does not start with 'erDiagram'")
    prov = _provenance()
    return (
        DesignArtifact(
            id="DFD-1",
            kind="dfd",
            title=str(dfd["title"]),
            source=str(dfd["mermaid"]),
            notes=str(dfd.get("notes", "")),
            provenance=prov,
        ),
        DesignArtifact(
            id="ER-1",
            kind="er",
            title=str(er["title"]),
            source=str(er["mermaid"]),
            notes=str(er.get("notes", "")),
            provenance=prov,
        ),
    )


# --- stories ---------------------------------------------------------------


def stories(epic: Epic, assessment: Assessment) -> tuple[UserStory, ...]:
    streams = ", ".join(s.value for s in Stream)
    task_lines = "\n".join(
        f"- {t.id} [{t.stream.value}/{t.coverage.value}] {t.summary}" for t in assessment.tasks
    )
    prompt = f"""Here is a business epic:

---
{epic.body}
---

The approved assessment routed it into these tasks:
{task_lines}

The design is signed off. Break the epic into exactly 3 user stories, each
decomposed into 1-3 executable tasks. Allowed stream values: {streams};
allowed coverage values: agentic, ai_assisted_external, manual.

Requirements:
- Every acceptance criterion id must be claimed by some task's "satisfies"
  list — full traceability, no orphan criteria.
- Exactly one task overall must be stream "frontend" with coverage "agentic"
  whose summary is building the plan-sponsor disability claim submission page
  (identify member from policy number + member id, pre-populate member
  details, claim details, multiple document upload, confirmation with a
  reference number and a visible status). That task is executed by the
  automated lane.
- Tasks on the externally-owned system of record are "ai_assisted_external"
  or "manual" with owning_team set — never agentic.
- Anything resting on the epic's open questions goes in "assumptions".

JSON schema:
{{"stories": [{{"id": "US-1", "title": str, "narrative": str,
"acceptance": [{{"id": "US-1-AC1", "text": str}}],
"streams": [str], "estimate_points": int, "assumptions": [str],
"tasks": [{{"id": "US-1-T1", "summary": str, "stream": str, "coverage": str,
"estimate_days": float, "satisfies": [str], "depends_on": [str],
"owning_team": str | null}}]}}]}}"""
    data = parse_json_block(
        complete(prompt, system=_SYSTEM, json_mode=True, cache_key="s7:stories")
    )
    prov = _provenance()
    built: list[UserStory] = []
    for s in data["stories"]:
        story_id = str(s["id"])
        tasks = tuple(
            Task(
                id=str(t["id"]),
                story_id=story_id,
                summary=str(t["summary"]),
                stream=Stream(t["stream"]),
                coverage=Coverage(t["coverage"]),
                estimate_days=float(t["estimate_days"]),
                provenance=prov,
                satisfies=tuple(str(x) for x in t.get("satisfies", [])),
                depends_on=tuple(str(x) for x in t.get("depends_on", [])),
                owning_team=t.get("owning_team"),
            )
            for t in s.get("tasks", [])
        )
        built.append(
            UserStory(
                id=story_id,
                title=str(s["title"]),
                narrative=str(s["narrative"]),
                acceptance=tuple(
                    AcceptanceCriterion(id=str(a["id"]), text=str(a["text"]))
                    for a in s.get("acceptance", [])
                ),
                streams=tuple(Stream(x) for x in s.get("streams", [])),
                estimate_points=int(s.get("estimate_points", 0)),
                provenance=prov,
                epic_id=epic.id,
                assumptions=tuple(str(x) for x in s.get("assumptions", [])),
                tasks=tasks,
            )
        )
    return tuple(built)
