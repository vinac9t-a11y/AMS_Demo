"""Intake engine rules — the ones no endpoint may route around.

Every test patches `s7_delivery.intake.complete`, so nothing here touches a
provider or a recording. What is under test is the module's own contract: the
question cap, the story quality bar, roster-only assignment, and coverage
being computed rather than believed.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s7_delivery import intake

EPIC = "# EPIC-T-1 — Test epic\n\n" + "The business context of a test epic. " * 20

QUESTIONS = json.dumps(
    {"needs_clarification": True, "questions": ["What is the deadline?"]}
)


def _story(story_id: str = "S7-INT-1", **overrides) -> dict:
    story = {
        "id": story_id,
        "title": "Do the thing",
        "narrative": "As a sponsor, I want the thing, so that outcome.",
        "acceptance": [{"id": "AC-1", "text": "Given x, when y, then z."}],
        "streams": ["api"],
        "estimate_points": 3,
        "task_type": "feature",
        "target_component": "portal API",
        "impacts": "adds an endpoint",
        "feature_flag": "thing_enabled",
        "rollback_plan": "disable the flag",
        "depends_on": [],
        "satisfies": ["R1"],
        "assignee": "Ravi Kumar",
        "assumptions": [],
    }
    story.update(overrides)
    return story


def _plan(**overrides) -> str:
    plan = {
        "needs_clarification": False,
        "requirements": [{"id": "R1", "text": "The thing must exist."}],
        "assumptions": [],
        "stories": [_story(), _story("S7-INT-2"), _story("S7-INT-3")],
        "sprints": [
            {"id": "Sprint 1", "goal": "Ship it", "story_ids": ["S7-INT-1", "S7-INT-2", "S7-INT-3"]}
        ],
    }
    plan.update(overrides)
    return json.dumps(plan)


def _session_with_plan(plan_json: str) -> intake.IntakeSession:
    with patch.object(intake, "complete", return_value=plan_json):
        return intake.start_session(EPIC)


def test_questions_then_plan_round_trip():
    with patch.object(intake, "complete", return_value=QUESTIONS):
        session = intake.start_session(EPIC)
    assert session.pending_questions == ["What is the deadline?"]
    assert session.plan is None

    with patch.object(intake, "complete", return_value=_plan()):
        intake.submit_answers(session, ["Friday"])
    assert session.plan is not None
    assert session.plan.unmapped_requirements() == ()
    assert [s.id for s in session.plan.stories] == ["S7-INT-1", "S7-INT-2", "S7-INT-3"]
    # Two calls, both measured.
    assert len(session.activity) == 2


def test_question_cap_is_a_prompt_bug_not_a_loop():
    with patch.object(intake, "complete", return_value=QUESTIONS):
        session = intake.start_session(EPIC)
        intake.submit_answers(session, ["a1"])  # round 2 of questions — at the cap
        with pytest.raises(LLMError, match="cap"):
            intake.submit_answers(session, ["a2"])  # model asks a third time


def test_skip_forces_a_plan():
    with patch.object(intake, "complete", return_value=QUESTIONS):
        session = intake.start_session(EPIC)
    with patch.object(intake, "complete", return_value=_plan()):
        intake.skip_to_plan(session)
    assert session.plan is not None


def test_unmapped_requirement_is_computed_not_believed():
    plan = _plan(
        requirements=[
            {"id": "R1", "text": "The thing."},
            {"id": "R2", "text": "The other thing nobody claimed."},
        ]
    )
    session = _session_with_plan(plan)
    assert session.plan.unmapped_requirements() == ("R2",)


def test_story_below_quality_bar_is_rejected():
    plan = _plan(stories=[_story(rollback_plan=""), _story("S7-INT-2"), _story("S7-INT-3")])
    with pytest.raises(LLMError, match="quality bar"):
        _session_with_plan(plan)


def test_assignee_must_be_on_roster():
    plan = _plan(
        stories=[_story(assignee="A. Nonexistent"), _story("S7-INT-2"), _story("S7-INT-3")]
    )
    with pytest.raises(LLMError, match="not on the team"):
        _session_with_plan(plan)


def test_assignee_streams_must_cover_story():
    # Priya Nair covers test only; an api story cannot be hers.
    plan = _plan(stories=[_story(assignee="Priya Nair"), _story("S7-INT-2"), _story("S7-INT-3")])
    with pytest.raises(LLMError, match="cover"):
        _session_with_plan(plan)


def test_sprints_must_place_every_story_exactly_once():
    plan = _plan(sprints=[{"id": "Sprint 1", "goal": "g", "story_ids": ["S7-INT-1"]}])
    with pytest.raises(LLMError, match="exactly once"):
        _session_with_plan(plan)


def test_tiny_epic_is_refused():
    with pytest.raises(LLMError, match="not enough"):
        intake.start_session("do a thing")


# ---- human review of the draft plan ----------------------------------------


def test_reassign_follows_the_same_rules_as_the_model():
    session = _session_with_plan(_plan())
    # Sofia covers system_of_record; the api story also lists only api — so
    # she is not eligible, exactly as she would not be for the model.
    with pytest.raises(intake.ReviewError, match="streams"):
        intake.reassign_story(session, "S7-INT-1", "Sofia Marchetti")
    with pytest.raises(intake.ReviewError, match="not on the team"):
        intake.reassign_story(session, "S7-INT-1", "A. Nonexistent")
    with pytest.raises(intake.ReviewError, match="No story"):
        intake.reassign_story(session, "S7-INT-99", "Ravi Kumar")


def test_reassign_updates_plan_and_review_log():
    plan = _plan(
        stories=[
            _story(streams=["api", "system_of_record"]),
            _story("S7-INT-2"),
            _story("S7-INT-3"),
        ]
    )
    session = _session_with_plan(plan)
    intake.reassign_story(session, "S7-INT-1", "Sofia Marchetti")
    assert session.plan.stories[0].assignee == "Sofia Marchetti"
    assert session.review_log[-1].action == "reassign"
    assert "Ravi Kumar → Sofia Marchetti" in session.review_log[-1].detail


def test_points_must_stay_on_the_scale():
    session = _session_with_plan(_plan())
    with pytest.raises(intake.ReviewError, match="Points"):
        intake.set_story_points(session, "S7-INT-1", 4)
    intake.set_story_points(session, "S7-INT-1", 8)
    assert session.plan.stories[0].estimate_points == 8
    assert session.plan.points_by_assignee()["Ravi Kumar"] == 8 + 3 + 3


def test_move_story_keeps_every_story_in_exactly_one_sprint():
    plan = _plan(
        sprints=[
            {"id": "Sprint 1", "goal": "g", "story_ids": ["S7-INT-1", "S7-INT-2"]},
            {"id": "Sprint 2", "goal": "g", "story_ids": ["S7-INT-3"]},
        ]
    )
    session = _session_with_plan(plan)
    intake.move_story(session, "S7-INT-1", "Sprint 2")
    placed = [sid for s in session.plan.sprints for sid in s.story_ids]
    assert sorted(placed) == ["S7-INT-1", "S7-INT-2", "S7-INT-3"]
    assert "S7-INT-1" in session.plan.sprints[1].story_ids
    with pytest.raises(intake.ReviewError, match="No sprint"):
        intake.move_story(session, "S7-INT-1", "Sprint 9")


def test_approval_needs_a_name_and_locks_the_plan():
    session = _session_with_plan(_plan())
    with pytest.raises(intake.ReviewError, match="name"):
        intake.approve_plan(session, "   ")
    intake.approve_plan(session, "Dana Cole", note="Looks right.")
    assert session.plan_status == "approved"
    assert session.review_log[-1].action == "approve"
    # Locked: every edit path refuses, including another approval.
    with pytest.raises(intake.ReviewError, match="locked"):
        intake.set_story_points(session, "S7-INT-1", 5)
    with pytest.raises(intake.ReviewError, match="locked"):
        intake.reassign_story(session, "S7-INT-1", "Ravi Kumar")
    with pytest.raises(intake.ReviewError, match="locked"):
        intake.request_revision(session, "please change everything")


def test_revision_replaces_the_plan_and_is_capped():
    session = _session_with_plan(_plan())
    revised = _plan(
        stories=[
            _story(estimate_points=13),
            _story("S7-INT-2"),
            _story("S7-INT-3"),
        ]
    )
    with patch.object(intake, "complete", return_value=revised):
        intake.request_revision(session, "S7-INT-1 is underestimated, raise it")
    assert session.plan.stories[0].estimate_points == 13
    assert session.revisions_used == 1
    assert session.review_log[-1].action == "revision"

    with pytest.raises(intake.ReviewError, match="feedback"):
        intake.request_revision(session, "meh")

    with patch.object(intake, "complete", return_value=revised):
        intake.request_revision(session, "now split the upload story in two")
    with pytest.raises(intake.ReviewError, match="cap"):
        intake.request_revision(session, "one more change please, again")


def test_revision_output_faces_the_same_validator():
    session = _session_with_plan(_plan())
    bad = _plan(stories=[_story(rollback_plan=""), _story("S7-INT-2"), _story("S7-INT-3")])
    with patch.object(intake, "complete", return_value=bad):
        with pytest.raises(LLMError, match="quality bar"):
            intake.request_revision(session, "tighten the rollback plans please")
