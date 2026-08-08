"""Stage orchestration for the S7 project lane.

    epic intake -> AI assessment -> design/DFD -> human review gate -> stories

The one invariant this module exists to enforce: **story breakdown does not run
until the gate is approved.** It is enforced here, in `build_state`, rather than
in the console or the API, so that no caller can route around it by calling a
different entry point. The gate is load-bearing, not decorative.

Artifacts currently come from `s7_delivery.staged` and are labelled
`Provenance.STAGED`. Sprint 3 swaps that source for real `common.llm` calls with
committed recordings; nothing else in this module or above it changes.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from s7_delivery import staged
from s7_delivery.models import (
    Assessment,
    DesignArtifact,
    Epic,
    GateDecision,
    Provenance,
    ReviewGate,
    Task,
    UserStory,
)

EPIC_PATH = Path(__file__).resolve().parent.parent / "crs" / "EPIC-S7-001.md"

STORIES_LOCKED_REASON = (
    "Story breakdown runs only after the human review gate is approved. "
    "This is the design step the client's brief explicitly asked for — an epic "
    "that jumps straight to stories skips it."
)


class PipelineError(Exception):
    """Raised when a stage is driven out of order or with invalid input."""


@dataclass(frozen=True)
class EpicDocument:
    """An epic plus the structure the console renders it from."""

    epic: Epic
    application: str
    summary: str
    sections: tuple[tuple[str, str], ...]
    open_questions: tuple[str, ...]


@dataclass(frozen=True)
class PipelineState:
    """Everything the console needs to draw, in one object."""

    document: EpicDocument
    assessment: Assessment
    design: tuple[DesignArtifact, ...]
    gate: ReviewGate
    stories: tuple[UserStory, ...]


# --- epic intake -----------------------------------------------------------


def load_epic(path: Path | None = None) -> EpicDocument:
    """Parse the epic markdown into the structure the console renders.

    Parsed rather than hardcoded so that editing `crs/EPIC-S7-001.md` — the
    thing a business analyst would actually hand over — changes the demo.
    """
    source = path or EPIC_PATH
    if not source.exists():
        raise PipelineError(f"Epic not found at {source}")
    text = source.read_text(encoding="utf-8")

    title_match = re.search(r"^#\s+(?P<id>[\w-]+)\s+[—-]\s+(?P<title>.+)$", text, re.MULTILINE)
    if not title_match:
        raise PipelineError(f"Epic at {source} has no '# <ID> — <title>' heading")
    epic_id = title_match.group("id").strip()
    title = title_match.group("title").strip()

    application = _table_value(text, "Target application") or "Unspecified"
    summary = _blockquote_after(text, "## 3.") or title

    sections = tuple(
        (heading, body)
        for heading, body in _numbered_sections(text)
        if not heading.lower().startswith("open questions")
    )
    open_questions = _open_questions(text)

    epic = Epic(
        id=epic_id,
        title=title,
        body=text,
        source_path=str(source),
        provenance=Provenance.HUMAN,
    )
    return EpicDocument(
        epic=epic,
        application=application,
        summary=summary,
        sections=sections,
        open_questions=open_questions,
    )


def _table_value(text: str, label: str) -> str | None:
    match = re.search(rf"^\|\s*\*\*{re.escape(label)}\*\*\s*\|\s*(?P<v>[^|]+?)\s*\|", text, re.M)
    return match.group("v").strip() if match else None


def _blockquote_after(text: str, marker: str) -> str | None:
    idx = text.find(marker)
    if idx == -1:
        return None
    quote = re.search(r"^>\s*(?P<q>.+?)(?=\n\n)", text[idx:], re.MULTILINE | re.DOTALL)
    if not quote:
        return None
    return " ".join(line.lstrip("> ").strip() for line in quote.group("q").splitlines()).strip()


def _numbered_sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) for each `## <n>. <Heading>` section."""
    pattern = re.compile(r"^##\s+\d+\.\s+(?P<heading>.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((match.group("heading").strip(), body))
    return sections


def _open_questions(text: str) -> tuple[str, ...]:
    """Pull the SME-validation bullets out of the epic's open-questions section.

    These must reach the UI intact. CLAUDE.md is explicit that anything resting
    on them is an assumption until an SME confirms it, so burying them would
    defeat the point of writing them down.
    """
    for heading, body in _numbered_sections(text):
        if heading.lower().startswith("open questions"):
            bullets = re.findall(r"^-\s+(?P<q>.+?)(?=\n(?:-|\n|>)|\Z)", body, re.MULTILINE | re.S)
            return tuple(" ".join(b.split()) for b in bullets)
    return ()


# --- the pipeline ----------------------------------------------------------


def initial_gate(epic_id: str) -> ReviewGate:
    return ReviewGate(epic_id=epic_id, decision=GateDecision.PENDING)


def _ai_artifacts_enabled() -> bool:
    """True when S7_ARTIFACTS=ai selects the recorded model-generated stages."""
    return os.environ.get("S7_ARTIFACTS", "staged").lower() == "ai"


def _ai_stage(name: str, produce, fallback):
    """Run a generated stage, falling back to its staged twin on any failure.

    A replay miss, malformed JSON, or invalid diagram must degrade to a badged
    STAGED artifact rather than a dead demo — loudly, so a silent fallback
    never masquerades as a recording.
    """
    try:
        return produce()
    except Exception as exc:  # noqa: BLE001 — any stage failure means fall back
        print(
            f"[s7] AI-generated {name} unavailable ({type(exc).__name__}: {exc}); "
            "falling back to STAGED artifact",
            file=sys.stderr,
        )
        return fallback()


def build_state(gate: ReviewGate | None = None, *, epic_path: Path | None = None) -> PipelineState:
    """Assemble the full pipeline state for a given gate decision.

    Stories are produced **only** when the gate is approved. That check lives
    here so every caller inherits it.
    """
    document = load_epic(epic_path)
    current = gate or initial_gate(document.epic.id)

    if _ai_artifacts_enabled():
        from s7_delivery import generate

        epic = document.epic
        assessment = _ai_stage("assessment", lambda: generate.assessment(epic), staged.assessment)
        design = _ai_stage("design", lambda: generate.design(epic, assessment), staged.design)
        if current.may_proceed:
            stories = _ai_stage(
                "stories", lambda: generate.stories(epic, assessment), staged.stories
            )
        else:
            stories = ()
    else:
        assessment = staged.assessment()
        design = staged.design()
        stories = staged.stories() if current.may_proceed else ()

    return PipelineState(
        document=document,
        assessment=assessment,
        design=design,
        gate=current,
        stories=stories,
    )


def decide(epic_id: str, *, decision: str, reviewer: str, comment: str = "") -> ReviewGate:
    """Record a review decision.

    A reviewer name is required: an unattributed approval is a rubber stamp,
    which is the failure mode this gate exists to prevent.
    """
    try:
        parsed = GateDecision(decision)
    except ValueError as exc:
        allowed = ", ".join(d.value for d in GateDecision)
        raise PipelineError(
            f"Unknown gate decision {decision!r}; expected one of: {allowed}"
        ) from exc

    if parsed is GateDecision.PENDING:
        raise PipelineError("Cannot decide a gate as 'pending'; use reset instead")
    if not reviewer.strip():
        raise PipelineError("A reviewer name is required to decide the gate")

    return ReviewGate(
        epic_id=epic_id,
        decision=parsed,
        reviewer=reviewer.strip(),
        decided_at=datetime.now(UTC),
        comment=comment.strip(),
    )


# --- serialisation ---------------------------------------------------------

_INLINE_MARKS = re.compile(r"\*\*|__|(?<!\w)[*_](?!\w)|`")


def _clean_inline(text: str) -> str:
    """Strip inline markdown emphasis markers, keeping the words."""
    return _INLINE_MARKS.sub("", text).strip()


def _to_blocks(body: str) -> list[dict[str, Any]]:
    """Convert a markdown section body into render-ready blocks.

    The console renders structured blocks rather than raw markdown. Handing a
    UI raw markdown means literal `**bold**` and bullet lists flattened into a
    wall of prose on screen — which is exactly what a client evaluation panel
    would see. Doing the conversion here keeps the frontend free of a markdown
    parser it would otherwise need to vendor.
    """
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    items: list[str] = []
    ordered = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append({"type": "paragraph", "text": _clean_inline(" ".join(paragraph))})
            paragraph.clear()

    def flush_list() -> None:
        if items:
            blocks.append(
                {
                    "type": "list",
                    "ordered": ordered,
                    "items": [_clean_inline(i) for i in items],
                }
            )
            items.clear()

    for raw in body.splitlines():
        stripped = raw.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("|"):
            # Markdown table rows. The epic's metadata table is already surfaced
            # as dedicated fields, so rendering it twice adds nothing.
            continue

        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
            if not stripped:
                continue
            flush_list()
            paragraph.append(stripped)
            continue

        bullet = re.match(r"^[-*]\s+(?P<text>.*)$", stripped)
        numbered = re.match(r"^\d+\.\s+(?P<text>.*)$", stripped)

        if bullet or numbered:
            flush_paragraph()
            is_ordered = numbered is not None
            if items and is_ordered != ordered:
                flush_list()
            ordered = is_ordered
            items.append((numbered or bullet).group("text"))
            continue

        if items and raw.startswith((" ", "\t")):
            # An indented continuation of the bullet above it.
            items[-1] = f"{items[-1]} {stripped}"
            continue

        flush_list()
        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    return blocks


def to_payload(state: PipelineState) -> dict[str, Any]:
    """Serialise state to the frozen console API contract."""
    return {
        "epic": _epic_payload(state.document),
        "assessment": _assessment_payload(state.assessment),
        "design": [_design_payload(d) for d in state.design],
        "gate": _gate_payload(state.gate),
        "stories": [_story_payload(s) for s in state.stories],
        "stories_locked_reason": "" if state.gate.may_proceed else STORIES_LOCKED_REASON,
    }


def _epic_payload(document: EpicDocument) -> dict[str, Any]:
    return {
        "id": document.epic.id,
        "title": document.epic.title,
        "application": document.application,
        "summary": document.summary,
        "sections": [
            {"heading": h, "body": b, "blocks": _to_blocks(b)} for h, b in document.sections
        ],
        "open_questions": list(document.open_questions),
        "provenance": document.epic.provenance.value,
        "source_path": document.epic.source_path,
    }


def _assessment_payload(assessment: Assessment) -> dict[str, Any]:
    breakdown = assessment.coverage_breakdown()
    days_by_coverage: dict[str, float] = {}
    for task in assessment.tasks:
        days_by_coverage[task.coverage.value] = (
            days_by_coverage.get(task.coverage.value, 0.0) + task.estimate_days
        )
    return {
        "epic_id": assessment.epic_id,
        "provenance": assessment.provenance.value,
        "integration_note": assessment.integration_note,
        "generated_at": assessment.generated_at.isoformat(),
        "totals": {
            "task_count": len(assessment.tasks),
            "estimate_days": round(sum(t.estimate_days for t in assessment.tasks), 2),
        },
        "coverage_breakdown": [
            {
                "coverage": coverage.value,
                "share": share,
                "days": round(days_by_coverage.get(coverage.value, 0.0), 2),
            }
            for coverage, share in sorted(breakdown.items(), key=lambda kv: -kv[1])
        ],
        "tasks": [
            {
                "id": t.id,
                "summary": t.summary,
                "stream": t.stream.value,
                "coverage": t.coverage.value,
                "estimate_days": t.estimate_days,
                "rationale": t.rationale,
                "depends_on": list(t.depends_on),
                "blocked_by_external": t.blocked_by_external,
            }
            for t in assessment.tasks
        ],
    }


def _design_payload(artifact: DesignArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "title": artifact.title,
        "format": "mermaid",
        "source": artifact.source,
        "notes": artifact.notes,
        "provenance": artifact.provenance.value,
    }


def _gate_payload(gate: ReviewGate) -> dict[str, Any]:
    return {
        "epic_id": gate.epic_id,
        "decision": gate.decision.value,
        "reviewer": gate.reviewer,
        "decided_at": gate.decided_at.isoformat() if gate.decided_at else None,
        "comment": gate.comment,
        "may_proceed": gate.may_proceed,
    }


def _story_payload(story: UserStory) -> dict[str, Any]:
    return {
        "id": story.id,
        "title": story.title,
        "narrative": story.narrative,
        "acceptance": [{"id": a.id, "text": a.text} for a in story.acceptance],
        "streams": [s.value for s in story.streams],
        "estimate_points": story.estimate_points,
        "provenance": story.provenance.value,
        "epic_id": story.epic_id,
        "assumptions": list(story.assumptions),
        "tasks": [_task_payload(t) for t in story.tasks],
        "unsatisfied": list(story.unsatisfied()),
        "task_coverage": {
            c.value: share for c, share in story.coverage_breakdown().items()
        },
    }


def _task_payload(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "story_id": task.story_id,
        "summary": task.summary,
        "stream": task.stream.value,
        "coverage": task.coverage.value,
        "estimate_days": task.estimate_days,
        "provenance": task.provenance.value,
        "satisfies": list(task.satisfies),
        "depends_on": list(task.depends_on),
        "owning_team": task.owning_team,
        "runs_in_downstream_lane": task.runs_in_downstream_lane,
    }
