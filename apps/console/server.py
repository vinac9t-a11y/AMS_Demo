"""S7 delivery console — HTTP layer.

Thin on purpose. Every rule that matters (the gate blocking story breakdown,
what an artifact's provenance is) lives in `s7_delivery/pipeline.py`, so it
cannot be bypassed by calling a different endpoint. This module only translates
HTTP to that module and back.

Run it with `demo/run_console.sh`, or:

    uvicorn apps.console.server:app --reload

State is held in memory for a single presenter. That is deliberate for a demo:
no database to seed, and `POST /api/reset` returns it to a known state between
rehearsals.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from s7_delivery.models import ReviewGate
from s7_delivery.pipeline import (
    PipelineError,
    build_state,
    decide,
    initial_gate,
    load_epic,
    to_payload,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOWNSTREAM_DIR = REPO_ROOT / "artifacts" / "EPIC-S7-001" / "downstream"

app = FastAPI(
    title="S7 Delivery Console",
    description="AI-assisted SDLC: epic -> assessment -> design -> review gate -> stories.",
)


@app.get("/api/health")
def get_health() -> dict[str, str]:
    """Lightweight browser/startup health check.

    Kept separate from /api/run so a UI smoke test can distinguish a server
    problem from a pipeline/artifact problem.
    """
    return {"status": "ok", "service": "s7-delivery-console"}


class _GateState:
    """The presenter's current review decision.

    Guarded by a lock because uvicorn may serve the reset and the poll from
    different threads, and a half-updated gate is exactly the kind of thing that
    misbehaves once in five demos.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gate: ReviewGate | None = None

    def get(self) -> ReviewGate:
        with self._lock:
            if self._gate is None:
                self._gate = initial_gate(load_epic().epic.id)
            return self._gate

    def set(self, gate: ReviewGate) -> ReviewGate:
        with self._lock:
            self._gate = gate
            return gate

    def reset(self) -> ReviewGate:
        with self._lock:
            self._gate = initial_gate(load_epic().epic.id)
            return self._gate


_state = _GateState()


class _ReleaseState:
    """The second human gate — release approval. Same discipline as the
    design gate: attributed, in-memory, reset between rehearsals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._value)

    def approve(self, reviewer: str, comment: str = "") -> dict[str, Any]:
        with self._lock:
            self._value = {
                "decision": "approved",
                "reviewer": reviewer,
                "decided_at": datetime.now(UTC).isoformat(),
                "comment": comment,
            }
            return dict(self._value)

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._value = {
                "decision": "pending",
                "reviewer": None,
                "decided_at": None,
                "comment": "",
            }


_release = _ReleaseState()


def _downstream_payload() -> dict[str, Any]:
    """The recorded downstream lane, read from the artifact plane.

    Absent files mean the lane has not been recorded — the console renders
    that honestly rather than failing.
    """
    events_path = DOWNSTREAM_DIR / "events.jsonl"
    review_path = DOWNSTREAM_DIR / "review.json"
    app_index = DOWNSTREAM_DIR / "app" / "index.html"

    events: list[dict[str, Any]] = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    review: dict[str, Any] = {}
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))

    lane_task_id = None
    if events:
        first = events[0].get("action", "")
        if first.startswith("picked up ") and ":" in first:
            lane_task_id = first.removeprefix("picked up ").split(":", 1)[0].strip()

    ok = bool(events) and events[-1].get("status") == "done"
    return {
        "events": events,
        "review": review,
        "lane_task_id": lane_task_id,
        "ok": ok,
        "app_available": app_index.exists(),
        "provenance": "replayed_ai" if events else "staged",
    }


def _gates_payload(run: dict[str, Any], downstream: dict[str, Any]) -> list[dict[str, Any]]:
    """The five-gate strip the overview renders. Computed, never asserted."""
    design_gate = run.get("gate") or {}
    stories = run.get("stories") or []
    release = _release.get()

    g1 = design_gate.get("decision", "pending")

    if stories:
        g2 = "approved" if all(not s.get("unsatisfied") for s in stories) else "pending"
    else:
        g2 = "pending"

    verdict = downstream["review"].get("verdict")
    g3 = {"pass": "approved", "fail": "rejected"}.get(verdict, "pending")

    g4 = release["decision"] if g3 == "approved" else "pending"

    return [
        {"id": "G0", "label": "Intake complete", "status": "approved",
         "detail": "Epic parsed and loaded", "target": "stage-epic"},
        {"id": "G1", "label": "Design sign-off", "status": g1,
         "detail": "Human review of assessment and design", "target": "stage-gate"},
        {"id": "G2", "label": "AC coverage", "status": g2,
         "detail": "Every acceptance criterion claimed by a task", "target": "stage-stories"},
        {"id": "G3", "label": "Independent review", "status": g3,
         "detail": "Second model verifies the build against the criteria", "target": "stage-downstream"},
        {"id": "G4", "label": "Release", "status": g4,
         "detail": "Human approves the release", "target": "stage-downstream"},
    ]


class GateRequest(BaseModel):
    decision: str = Field(description="'approved' or 'rejected'")
    reviewer: str = Field(
        description="Who decided. Required — an unattributed gate is a rubber stamp."
    )
    comment: str = ""


def _payload() -> dict[str, Any]:
    run = to_payload(build_state(_state.get()))
    downstream = _downstream_payload()
    run["release_gate"] = _release.get()
    run["gates"] = _gates_payload(run, downstream)
    return run


@app.exception_handler(PipelineError)
async def _pipeline_error_handler(_request: Any, exc: PipelineError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/run")
def get_run() -> dict[str, Any]:
    """The complete pipeline state. The console renders entirely from this."""
    return _payload()


@app.post("/api/gate")
def post_gate(request: GateRequest) -> dict[str, Any]:
    """Record the human review decision.

    Approval is what unlocks story breakdown; rejection deliberately leaves it
    locked, so the demo can show the gate actually changing the outcome.
    """
    try:
        gate = decide(
            _state.get().epic_id,
            decision=request.decision,
            reviewer=request.reviewer,
            comment=request.comment,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _state.set(gate)
    return _payload()


@app.get("/api/downstream")
def get_downstream() -> dict[str, Any]:
    """The recorded downstream lane — events feed, review verdict, app."""
    return _downstream_payload()


class ReleaseRequest(BaseModel):
    reviewer: str = Field(description="Who approved the release. Required.")
    comment: str = ""


@app.post("/api/release")
def post_release(request: ReleaseRequest) -> dict[str, Any]:
    """Record release approval — the second human gate.

    Refused while the independent review has not passed: a human approving a
    release nobody verified is exactly what the gate order exists to prevent.
    """
    if not request.reviewer.strip():
        raise HTTPException(status_code=400, detail="A reviewer name is required")
    downstream = _downstream_payload()
    if downstream["review"].get("verdict") != "pass":
        raise HTTPException(
            status_code=400,
            detail="Release is locked until the independent review (G3) passes",
        )
    _release.approve(request.reviewer.strip(), request.comment.strip())
    return _payload()


@app.post("/api/reset")
def post_reset() -> dict[str, Any]:
    """Return both gates to pending — the between-rehearsals reset."""
    _state.reset()
    _release.reset()
    return _payload()


# The generated application — the downstream lane's real output, served so
# the demo's last click opens it. Mounted before "/" so its path wins.
if (DOWNSTREAM_DIR / "app").is_dir():
    app.mount(
        "/generated-app",
        StaticFiles(directory=DOWNSTREAM_DIR / "app", html=True),
        name="generated-app",
    )

# Mounted last so the API routes above win. `html=True` serves index.html at /.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="console")
