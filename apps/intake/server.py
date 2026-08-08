"""S7 epic intake — HTTP layer.

Thin on purpose, same as the console: every rule that matters (the question
cap, the story quality bar, requirement coverage, roster-only assignment)
lives in `s7_delivery/intake.py` and cannot be bypassed from here.

Run it with `demo/run_intake.sh`, or:

    uvicorn apps.intake.server:app --reload

State is one in-memory session for a single presenter, reset between
rehearsals with `POST /api/reset`.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from common.llm import LLMError
from s7_delivery.intake import (
    MAX_CLARIFICATION_ROUNDS,
    MAX_REVISION_ROUNDS,
    POINT_SCALE,
    SAMPLE_EPIC_PATH,
    TEAM,
    DeliveryPlan,
    IntakeSession,
    ReviewError,
    approve_plan,
    move_story,
    reassign_story,
    request_revision,
    set_story_points,
    skip_to_plan,
    start_session,
    submit_answers,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="S7 Epic Intake",
    description="Epic in -> clarifying questions -> sprint plan, stories and owners.",
)


class _SessionState:
    """The presenter's current session, lock-guarded like the console's gate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: IntakeSession | None = None

    def get(self) -> IntakeSession | None:
        with self._lock:
            return self._session

    def set(self, session: IntakeSession | None) -> None:
        with self._lock:
            self._session = session


_state = _SessionState()


class EpicRequest(BaseModel):
    text: str
    title: str = ""


class AnswersRequest(BaseModel):
    answers: list[str]


class ReassignRequest(BaseModel):
    story_id: str
    assignee: str


class PointsRequest(BaseModel):
    story_id: str
    points: int


class MoveRequest(BaseModel):
    story_id: str
    sprint_id: str


class RevisionRequest(BaseModel):
    feedback: str


class ApproveRequest(BaseModel):
    approver: str
    note: str = ""


@app.exception_handler(LLMError)
async def _llm_error_handler(_request: Any, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ReviewError)
async def _review_error_handler(_request: Any, exc: ReviewError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _plan_payload(plan: DeliveryPlan) -> dict[str, Any]:
    return {
        "requirements": [asdict(r) for r in plan.requirements],
        "assumptions": list(plan.assumptions),
        "sprints": [asdict(s) for s in plan.sprints],
        "stories": [
            {
                **asdict(story),
                "streams": [s.value for s in story.streams],
                "provenance": story.provenance.value,
            }
            for story in plan.stories
        ],
        "provenance": plan.provenance.value,
        # Computed here, never taken from the model's own claim.
        "unmapped_requirements": list(plan.unmapped_requirements()),
        "points_by_assignee": plan.points_by_assignee(),
    }


def _payload() -> dict[str, Any]:
    session = _state.get()
    team = [
        {"name": m.name, "title": m.title, "streams": [s.value for s in m.streams]}
        for m in TEAM
    ]
    if session is None:
        return {"status": "empty", "max_rounds": MAX_CLARIFICATION_ROUNDS, "team": team}
    return {
        "status": "planned" if session.plan else "clarifying",
        "epic_title": session.epic_title,
        "rounds_used": session.rounds_used,
        "max_rounds": MAX_CLARIFICATION_ROUNDS,
        "questions": session.pending_questions,
        "transcript": session.transcript,
        "activity": [asdict(entry) for entry in session.activity],
        "plan": _plan_payload(session.plan) if session.plan else None,
        "team": team,
        # The human review layer: draft until a named approver locks it.
        "plan_status": session.plan_status,
        "revisions_used": session.revisions_used,
        "max_revisions": MAX_REVISION_ROUNDS,
        "point_scale": list(POINT_SCALE),
        "review_log": [asdict(entry) for entry in session.review_log],
        "approval": {
            "by": session.approved_by,
            "at": session.approved_at,
            "note": session.approval_note,
        } if session.approved_by else None,
    }


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """Everything the page renders, in one shape."""
    return _payload()


@app.get("/api/sample")
def get_sample() -> dict[str, str]:
    """The seeded epic, for the one-click demo path."""
    return {"text": SAMPLE_EPIC_PATH.read_text(encoding="utf-8")}


@app.post("/api/epic")
def post_epic(request: EpicRequest) -> dict[str, Any]:
    """Register an epic and run the first pass."""
    if _state.get() is not None:
        raise HTTPException(
            status_code=409, detail="A session is already open. Reset it first."
        )
    _state.set(start_session(request.text, epic_title=request.title))
    return _payload()


@app.post("/api/answers")
def post_answers(request: AnswersRequest) -> dict[str, Any]:
    """Answer the open questions; the model asks again or plans."""
    session = _state.get()
    if session is None:
        raise HTTPException(status_code=409, detail="No open session.")
    if len(request.answers) != len(session.pending_questions):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(session.pending_questions)} answers.",
        )
    submit_answers(session, request.answers)
    return _payload()


@app.post("/api/skip")
def post_skip() -> dict[str, Any]:
    """No more questions — plan from what is known, assumptions stated."""
    session = _state.get()
    if session is None:
        raise HTTPException(status_code=409, detail="No open session.")
    skip_to_plan(session)
    return _payload()


def _open_session() -> IntakeSession:
    session = _state.get()
    if session is None:
        raise HTTPException(status_code=409, detail="No open session.")
    return session


@app.post("/api/plan/reassign")
def post_reassign(request: ReassignRequest) -> dict[str, Any]:
    """Hand a story to another team member — rules enforced in the engine."""
    reassign_story(_open_session(), request.story_id, request.assignee)
    return _payload()


@app.post("/api/plan/points")
def post_points(request: PointsRequest) -> dict[str, Any]:
    """Re-estimate a story on the plan's point scale."""
    set_story_points(_open_session(), request.story_id, request.points)
    return _payload()


@app.post("/api/plan/move")
def post_move(request: MoveRequest) -> dict[str, Any]:
    """Move a story to another sprint."""
    move_story(_open_session(), request.story_id, request.sprint_id)
    return _payload()


@app.post("/api/plan/revise")
def post_revise(request: RevisionRequest) -> dict[str, Any]:
    """Human feedback in, revised plan out — through the same validator."""
    request_revision(_open_session(), request.feedback)
    return _payload()


@app.post("/api/plan/approve")
def post_approve(request: ApproveRequest) -> dict[str, Any]:
    """A named human signs off; the plan locks."""
    approve_plan(_open_session(), request.approver, request.note)
    return _payload()


@app.post("/api/reset")
def post_reset() -> dict[str, Any]:
    """Drop the session — the between-rehearsals reset."""
    _state.set(None)
    return _payload()


# Mounted last so the API routes above win. `html=True` serves index.html at /.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="intake")
