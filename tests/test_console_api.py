"""Console API tests.

The gate is the thing worth testing hardest. It is the beat the client's brief
asked for, and a gate that can be routed around is not a gate — so most of what
follows is attempts to get stories out of the pipeline without approving it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.console.server import app

STAGE_ARTIFACTS = ("epic", "assessment")


@pytest.fixture()
def client() -> TestClient:
    """A client with the gate reset, so tests cannot leak state into each other."""
    c = TestClient(app)
    c.post("/api/reset")
    return c


# --- the gate --------------------------------------------------------------


def test_stories_are_locked_before_the_gate(client: TestClient) -> None:
    body = client.get("/api/run").json()
    assert body["stories"] == []
    assert body["gate"]["decision"] == "pending"
    assert body["gate"]["may_proceed"] is False
    assert body["stories_locked_reason"]


def test_approval_unlocks_story_breakdown(client: TestClient) -> None:
    body = client.post(
        "/api/gate", json={"decision": "approved", "reviewer": "delivery lead"}
    ).json()
    assert body["gate"]["decision"] == "approved"
    assert len(body["stories"]) == 3
    assert body["stories_locked_reason"] == ""
    assert body["gate"]["decided_at"] is not None


def test_rejection_keeps_stories_locked(client: TestClient) -> None:
    body = client.post(
        "/api/gate",
        json={
            "decision": "rejected",
            "reviewer": "delivery lead",
            "comment": "SME questions in section 10 are still open",
        },
    ).json()
    assert body["gate"]["decision"] == "rejected"
    assert body["stories"] == []
    assert "section 10" in body["gate"]["comment"]


def test_gate_requires_a_named_reviewer(client: TestClient) -> None:
    """An unattributed approval is a rubber stamp."""
    response = client.post("/api/gate", json={"decision": "approved", "reviewer": "   "})
    assert response.status_code == 400
    assert client.get("/api/run").json()["stories"] == []


def test_gate_rejects_an_unknown_decision(client: TestClient) -> None:
    response = client.post("/api/gate", json={"decision": "probably", "reviewer": "lead"})
    assert response.status_code == 400


def test_gate_cannot_be_decided_as_pending(client: TestClient) -> None:
    """'pending' is a starting state, not a decision someone makes."""
    response = client.post("/api/gate", json={"decision": "pending", "reviewer": "lead"})
    assert response.status_code == 400


def test_reset_relocks_the_gate(client: TestClient) -> None:
    client.post("/api/gate", json={"decision": "approved", "reviewer": "lead"})
    assert len(client.get("/api/run").json()["stories"]) == 3

    body = client.post("/api/reset").json()
    assert body["gate"]["decision"] == "pending"
    assert body["stories"] == []


# --- provenance must survive serialisation ---------------------------------


def test_every_artifact_carries_provenance(client: TestClient) -> None:
    body = client.post("/api/gate", json={"decision": "approved", "reviewer": "lead"}).json()

    for key in STAGE_ARTIFACTS:
        assert body[key]["provenance"], f"{key} lost its provenance"
    for artifact in body["design"]:
        assert artifact["provenance"]
    for story in body["stories"]:
        assert story["provenance"]


def test_staged_artifacts_are_labelled_staged(client: TestClient) -> None:
    """Sprint 0 output is hand-written. It must not claim to be AI output.

    This test flips to `replayed_ai` in Sprint 3 — deliberately, and only when
    the artifacts really are recorded model output.
    """
    body = client.post("/api/gate", json={"decision": "approved", "reviewer": "lead"}).json()

    assert body["epic"]["provenance"] == "human"
    assert body["assessment"]["provenance"] == "staged"
    assert all(a["provenance"] == "staged" for a in body["design"])
    assert all(s["provenance"] == "staged" for s in body["stories"])


# --- the coverage model is the deliverable ---------------------------------


def test_coverage_is_reported_by_effort_and_adds_up(client: TestClient) -> None:
    assessment = client.get("/api/run").json()["assessment"]
    breakdown = assessment["coverage_breakdown"]

    assert sum(entry["share"] for entry in breakdown) == pytest.approx(1.0, abs=0.001)
    assert sum(entry["days"] for entry in breakdown) == assessment["totals"]["estimate_days"]

    agentic = next(e for e in breakdown if e["coverage"] == "agentic")
    assert 0.4 <= agentic["share"] <= 0.7, "an honest coverage claim, not a flattering one"


def test_the_external_blocker_is_visible(client: TestClient) -> None:
    """The manual change another team owns must not be quietly hidden."""
    tasks = client.get("/api/run").json()["assessment"]["tasks"]
    blocked = [t for t in tasks if t["blocked_by_external"]]

    assert len(blocked) == 1
    assert blocked[0]["stream"] == "system_of_record"
    assert blocked[0]["coverage"] == "manual"


def test_every_stream_routed_task_has_a_rationale(client: TestClient) -> None:
    for task in client.get("/api/run").json()["assessment"]["tasks"]:
        assert task["rationale"].strip(), f"{task['id']} claims a coverage class without saying why"


# --- the epic ---------------------------------------------------------------


def test_epic_open_questions_reach_the_ui(client: TestClient) -> None:
    """Unvalidated SME questions must be carried, not buried."""
    epic = client.get("/api/run").json()["epic"]
    assert len(epic["open_questions"]) == 5
    assert epic["application"].startswith("MapleSure")


def test_stories_carry_their_assumptions(client: TestClient) -> None:
    body = client.post("/api/gate", json={"decision": "approved", "reviewer": "lead"}).json()
    assert any(story["assumptions"] for story in body["stories"])
