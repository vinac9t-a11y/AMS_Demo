"""The coverage model is a deliverable, so its arithmetic gets a test.

CLAUDE.md: an honest 40-70% AI coverage that is articulated beats a claimed 100%
that does not survive a question. The specific way a claim like that goes wrong
is counting tasks instead of effort, so that is what these tests pin down.
"""

from __future__ import annotations

from datetime import UTC, datetime

from s7_delivery.models import (
    AcceptanceCriterion,
    AssessedTask,
    Assessment,
    Coverage,
    GateDecision,
    Provenance,
    ReviewGate,
    Stream,
    Task,
    UserStory,
)


def _task(task_id: str, coverage: Coverage, days: float) -> AssessedTask:
    return AssessedTask(
        id=task_id,
        summary=f"task {task_id}",
        stream=Stream.API,
        coverage=coverage,
        estimate_days=days,
        rationale="test fixture",
    )


def _assessment(*tasks: AssessedTask) -> Assessment:
    return Assessment(
        epic_id="EPIC-S7-001",
        tasks=tasks,
        integration_note="streams merge before integrated test",
        provenance=Provenance.REPLAYED_AI,
        generated_at=datetime.now(UTC),
    )


def test_coverage_is_weighted_by_effort_not_task_count() -> None:
    """Ten trivial agentic tasks beside one large manual one is not 91% AI."""
    tasks = [_task(f"T{i}", Coverage.AGENTIC, 0.5) for i in range(10)]
    tasks.append(_task("T-manual", Coverage.MANUAL, 15.0))
    breakdown = _assessment(*tasks).coverage_breakdown()

    assert breakdown[Coverage.AGENTIC] == 0.25
    assert breakdown[Coverage.MANUAL] == 0.75


def test_coverage_breakdown_sums_to_one() -> None:
    assessment = _assessment(
        _task("T1", Coverage.AGENTIC, 4.0),
        _task("T2", Coverage.AI_ASSISTED_EXTERNAL, 3.0),
        _task("T3", Coverage.MANUAL, 3.0),
    )
    assert sum(assessment.coverage_breakdown().values()) == 1.0


def test_empty_assessment_reports_nothing_rather_than_dividing_by_zero() -> None:
    assert _assessment().coverage_breakdown() == {}


def test_staged_provenance_is_the_one_that_demands_a_label() -> None:
    assert Provenance.STAGED.needs_label
    assert not Provenance.REPLAYED_AI.needs_label
    assert not Provenance.LIVE_AI.needs_label


def test_gate_blocks_until_approved() -> None:
    pending = ReviewGate(epic_id="EPIC-S7-001", decision=GateDecision.PENDING)
    rejected = ReviewGate(epic_id="EPIC-S7-001", decision=GateDecision.REJECTED)
    approved = ReviewGate(
        epic_id="EPIC-S7-001",
        decision=GateDecision.APPROVED,
        reviewer="delivery lead",
        decided_at=datetime.now(UTC),
    )

    assert not pending.may_proceed
    assert not rejected.may_proceed
    assert approved.may_proceed


def test_external_blocker_is_representable() -> None:
    """The system-of-record change another team owns, that others queue behind."""
    task = AssessedTask(
        id="T-SOR-1",
        summary="add field to member record",
        stream=Stream.SYSTEM_OF_RECORD,
        coverage=Coverage.MANUAL,
        estimate_days=10.0,
        rationale="owned by the platform team, not modifiable on this timeline",
        blocked_by_external=True,
    )
    assert task.blocked_by_external
    assert task.coverage is Coverage.MANUAL


# --- Task: the executable unit below a story (settled 2026-08-04) -------------


def _story(*tasks: Task, criteria: tuple[str, ...] = ("AC1", "AC2")) -> UserStory:
    return UserStory(
        id="S7-001-1",
        title="test story",
        narrative="as a tester, I want a fixture",
        acceptance=tuple(AcceptanceCriterion(c, f"criterion {c}") for c in criteria),
        streams=(Stream.API,),
        estimate_points=8,
        provenance=Provenance.STAGED,
        tasks=tasks,
    )


def _subtask(
    task_id: str,
    coverage: Coverage,
    days: float,
    satisfies: tuple[str, ...] = (),
) -> Task:
    return Task(
        id=task_id,
        story_id="S7-001-1",
        summary=f"task {task_id}",
        stream=Stream.API,
        coverage=coverage,
        estimate_days=days,
        provenance=Provenance.STAGED,
        satisfies=satisfies,
    )


def test_only_agentic_tasks_enter_the_downstream_lane() -> None:
    """The seam between the two scopes: everything else is done by hand."""
    agentic = _subtask("T1", Coverage.AGENTIC, 1.0)
    external = _subtask("T2", Coverage.AI_ASSISTED_EXTERNAL, 1.0)
    manual = _subtask("T3", Coverage.MANUAL, 1.0)

    assert agentic.runs_in_downstream_lane
    assert not external.runs_in_downstream_lane
    assert not manual.runs_in_downstream_lane


def test_unsatisfied_criteria_are_reported_not_hidden() -> None:
    story = _story(_subtask("T1", Coverage.AGENTIC, 1.0, satisfies=("AC1",)))
    assert story.unsatisfied() == ("AC2",)


def test_a_fully_decomposed_story_leaves_nothing_unsatisfied() -> None:
    story = _story(
        _subtask("T1", Coverage.AGENTIC, 1.0, satisfies=("AC1",)),
        _subtask("T2", Coverage.MANUAL, 2.0, satisfies=("AC2",)),
    )
    assert story.unsatisfied() == ()


def test_an_undecomposed_story_reports_every_criterion_rather_than_erroring() -> None:
    """A story past the gate but not yet broken down is a real state."""
    story = _story()
    assert story.unsatisfied() == ("AC1", "AC2")
    assert story.coverage_breakdown() == {}


def test_story_task_coverage_is_weighted_by_effort() -> None:
    """Same trap as the epic-level breakdown, one level down."""
    story = _story(
        _subtask("T1", Coverage.AGENTIC, 1.0, satisfies=("AC1",)),
        _subtask("T2", Coverage.AGENTIC, 1.0, satisfies=("AC1",)),
        _subtask("T3", Coverage.MANUAL, 6.0, satisfies=("AC2",)),
    )
    breakdown = story.coverage_breakdown()

    assert breakdown[Coverage.AGENTIC] == 0.25
    assert breakdown[Coverage.MANUAL] == 0.75


def test_a_task_owned_by_another_team_names_who_is_waited_on() -> None:
    task = Task(
        id="T-SOR-1",
        story_id="S7-001-1",
        summary="add field to member record",
        stream=Stream.SYSTEM_OF_RECORD,
        coverage=Coverage.AI_ASSISTED_EXTERNAL,
        estimate_days=10.0,
        provenance=Provenance.STAGED,
        owning_team="system-of-record platform team",
    )
    assert task.owning_team == "system-of-record platform team"
    assert not task.runs_in_downstream_lane
