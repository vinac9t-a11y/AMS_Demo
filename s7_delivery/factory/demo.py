"""Scripted demo scenarios (spec §20) — each drives a fresh run to a known
state through the same engine actions a presenter would click, so every gate
check, ledger append and role check runs for real. Nothing here bypasses the
engine; these are macros, not fixtures.
"""

from __future__ import annotations

from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, Role


def _intake_and_plan(eng: Engine) -> None:
    eng.intake_analyse(Role.PRODUCT_ANALYST)
    eng.intake_create_epic(Role.PRODUCT_ANALYST)
    eng.intake_pass_gate(Role.DELIVERY_LEAD)
    eng.planning_generate(Role.DELIVERY_LEAD)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau", "Plan approved for build")


def _task_id(eng: Engine, story_id: str) -> str:
    return next(
        t for t in eng.state()["build"]["tasks"] if t["story_id"] == story_id
    )["task_id"]


def _build_all(eng: Engine, *, stop_at_block: bool = False) -> None:
    order = ["US-001", "US-002", "US-003", "US-004", "US-005", "US-006", "US-007"]
    for story in order:
        tid = _task_id(eng, story)
        eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
        report = eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
        if report["result"] == "blocked":
            if stop_at_block:
                return
            eng.review_return_to_development(Role.INDEPENDENT_REVIEWER, tid)
            eng.task_generate_tests(Role.ENGINEERING_LEAD, tid)
            eng.task_develop(Role.ENGINEERING_LEAD, tid)
            eng.task_verify(Role.ENGINEERING_LEAD, tid)
            eng.task_submit_review(Role.ENGINEERING_LEAD, tid)
            eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)


def _approvals(eng: Engine) -> None:
    eng.release_approve(Role.BUSINESS_OWNER, "P. Moreau")
    eng.release_approve(Role.ENGINEERING_LEAD, "A. Osei")
    eng.release_approve(Role.QA_LEAD, "R. Tanaka")
    eng.release_approve(Role.RELEASE_MANAGER, "S. Lindqvist")


def happy_path(eng: Engine) -> None:
    """Full successful run: intake → plan → build (with the US-003
    correction cycle) → quality → approvals → deploy → handover."""
    _intake_and_plan(eng)
    _build_all(eng)
    eng.quality_run(Role.QA_LEAD)
    eng.quality_decide(Role.QA_LEAD)
    eng.release_request_approval(Role.RELEASE_MANAGER)
    _approvals(eng)
    eng.release_deploy(Role.RELEASE_MANAGER)
    eng.release_handover(Role.SUPPORT_LEAD)


def review_failure(eng: Engine) -> None:
    """Stops at the drama: US-003 blocked by independent review with one
    major gap on the equality boundary."""
    _intake_and_plan(eng)
    _build_all(eng, stop_at_block=True)


def missing_test_coverage(eng: Engine) -> None:
    """A task's test evidence loses a criterion's test; QC-03 fails and the
    quality gate blocks with the missing criterion named."""
    _intake_and_plan(eng)
    _build_all(eng)
    tasks = eng.store.read_json("build", "tasks.json")
    task = next(t for t in tasks if t["story_id"] == "US-004")
    task["tests"] = [t for t in task["tests"] if t["ac_id"] != "US-004-AC2"]
    eng.store.write_json(tasks, "build", "tasks.json")
    eng.quality_run(Role.QA_LEAD)
    try:
        eng.quality_decide(Role.QA_LEAD)
    except EngineError:
        pass  # the point: the gate blocks, and the run shows why


def staleness_demo(eng: Engine) -> None:
    """Approved and ready to deploy — then the SME ruling lands. Downstream
    artifacts stale, release blocked, self-correction left to the presenter."""
    _intake_and_plan(eng)
    _build_all(eng)
    eng.quality_run(Role.QA_LEAD)
    eng.quality_decide(Role.QA_LEAD)
    eng.release_request_approval(Role.RELEASE_MANAGER)
    _approvals(eng)
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    try:
        eng.release_deploy(Role.RELEASE_MANAGER)
    except EngineError:
        pass  # blocked on staleness — the state the demo wants to show


def release_rejected(eng: Engine) -> None:
    """The Business Owner rejects the release; the gate blocks with the
    rejection note on record."""
    _intake_and_plan(eng)
    _build_all(eng)
    eng.quality_run(Role.QA_LEAD)
    eng.quality_decide(Role.QA_LEAD)
    eng.release_request_approval(Role.RELEASE_MANAGER)
    eng.release_approve(
        Role.BUSINESS_OWNER, "P. Moreau",
        note="Hold: sponsor communications are not ready for this window",
        decision="rejected",
    )


SCENARIOS = {
    "happy-path": happy_path,
    "review-failure": review_failure,
    "missing-test-coverage": missing_test_coverage,
    "staleness": staleness_demo,
    "release-rejected": release_rejected,
    "full-run": happy_path,
}


def load(action: str) -> Engine:
    if action not in SCENARIOS:
        raise EngineError(
            f"Unknown demo scenario {action!r}; expected one of: "
            + ", ".join(sorted(SCENARIOS))
        )
    eng = Engine.create(DemoMode.SIMULATION)
    SCENARIOS[action](eng)
    return eng
