"""Build & independent review: test-first, the deliberate defect, correction.

The demonstration's core governance beat: US-003's first build implements the
absence-date rejection with `<` where US-003-AC3 says "on or before" (`<=`),
and its boundary test mirrors the same misreading — green tests over a
defective build. The independent reviewer verifies against the criterion and
blocks. NO PHASE SELF-APPROVES.
"""

import pytest

from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, GateId, Role, Stage, Status
from s7_delivery.factory.roles import PermissionError_


@pytest.fixture()
def eng(tmp_path):
    e = Engine.create(DemoMode.SIMULATION, root=tmp_path)
    e.intake_analyse(Role.PRODUCT_ANALYST)
    e.intake_create_epic(Role.PRODUCT_ANALYST)
    e.intake_pass_gate(Role.DELIVERY_LEAD)
    e.planning_generate(Role.DELIVERY_LEAD)
    e.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    return e


def task_of(eng, story_id):
    return next(t for t in eng.state()["build"]["tasks"] if t["story_id"] == story_id)


def complete_task(eng, story_id):
    tid = task_of(eng, story_id)["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    return tid


# --- ordering and prerequisites ---------------------------------------------


def test_dependent_task_cannot_start(eng):
    tid = task_of(eng, "US-003")["task_id"]  # depends on US-002
    with pytest.raises(EngineError, match="ready"):
        eng.task_start(Role.ENGINEERING_LEAD, tid)


def test_develop_requires_red_baseline(eng):
    tid = task_of(eng, "US-001")["task_id"]
    eng.task_start(Role.ENGINEERING_LEAD, tid)
    with pytest.raises(EngineError, match="test-first"):
        eng.task_develop(Role.ENGINEERING_LEAD, tid)


def test_tests_start_red_then_go_green(eng):
    tid = task_of(eng, "US-001")["task_id"]
    eng.task_start(Role.ENGINEERING_LEAD, tid)
    eng.task_generate_tests(Role.ENGINEERING_LEAD, tid)
    tests = task_of(eng, "US-001")["tests"]
    assert tests and all(t["initial_result"] == "failed" for t in tests)
    assert all(t["current_result"] == "failed" for t in tests)
    eng.task_develop(Role.ENGINEERING_LEAD, tid)
    tests = task_of(eng, "US-001")["tests"]
    assert all(t["current_result"] == "passed" for t in tests)
    assert all(t["initial_result"] == "failed" for t in tests), "red baseline preserved"


def test_review_requires_submission(eng):
    tid = task_of(eng, "US-001")["task_id"]
    with pytest.raises(EngineError, match="submitted"):
        eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)


def test_only_reviewer_reviews_and_cannot_develop(eng):
    tid = task_of(eng, "US-001")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    with pytest.raises(PermissionError_):
        eng.review_execute(Role.ENGINEERING_LEAD, tid)
    with pytest.raises(PermissionError_):
        eng.task_develop(Role.INDEPENDENT_REVIEWER, tid)


# --- clean pass -------------------------------------------------------------


def test_clean_task_passes_and_unlocks_dependents(eng):
    complete_task(eng, "US-001")
    assert task_of(eng, "US-001")["status"] == "completed"
    assert task_of(eng, "US-002")["status"] == "ready"
    assert task_of(eng, "US-003")["status"] == "not_started"


# --- the deliberate defect --------------------------------------------------


def test_us003_first_review_blocks_with_major_gap(eng):
    complete_task(eng, "US-001")
    complete_task(eng, "US-002")
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    report = eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    assert report["result"] == "blocked"
    assert report["major_gaps"] == 1
    assert report["findings"][0]["ac_id"] == "US-003-AC3"
    assert task_of(eng, "US-003")["status"] == "blocked"
    assert eng.gate(GateId.INDEPENDENT_REVIEW).status == Status.BLOCKED


def test_us003_defective_tests_were_green(eng):
    """The point of the beat: tests alone would have let this through."""
    complete_task(eng, "US-001")
    complete_task(eng, "US-002")
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    tests = task_of(eng, "US-003")["tests"]
    assert all(t["current_result"] == "passed" for t in tests)
    boundary = next(t for t in tests if t["ac_id"] == "US-003-AC3")
    assert "before_last_day_worked" in boundary["name"]
    assert "on_or_before" not in boundary["name"]


def test_blocked_task_cannot_rerun_without_return(eng):
    complete_task(eng, "US-001")
    complete_task(eng, "US-002")
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    with pytest.raises(EngineError, match="return"):
        eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)


def test_correction_cycle_passes_re_review(eng):
    complete_task(eng, "US-001")
    complete_task(eng, "US-002")
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)

    eng.review_return_to_development(Role.INDEPENDENT_REVIEWER, tid)
    assert task_of(eng, "US-003")["status"] == "in_progress"

    eng.task_generate_tests(Role.ENGINEERING_LEAD, tid)
    eng.task_develop(Role.ENGINEERING_LEAD, tid)
    eng.task_verify(Role.ENGINEERING_LEAD, tid)
    eng.task_submit_review(Role.ENGINEERING_LEAD, tid)
    report = eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)

    assert report["result"] == "passed"
    assert report["major_gaps"] == 0
    assert report["version"] == 2
    task = task_of(eng, "US-003")
    assert task["status"] == "completed"
    assert task["version"] == 2, "correction produced a new version, not an overwrite"
    boundary = next(t for t in task["tests"] if t["ac_id"] == "US-003-AC3")
    assert "on_or_before" in boundary["name"], "corrected test asserts the equality case"
    assert "Correction after independent review" in task["change_summary"]


def test_full_queue_completes_and_passes_g2(eng):
    for story in ["US-001", "US-002"]:
        complete_task(eng, story)
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    eng.review_return_to_development(Role.INDEPENDENT_REVIEWER, tid)
    eng.task_generate_tests(Role.ENGINEERING_LEAD, tid)
    eng.task_develop(Role.ENGINEERING_LEAD, tid)
    eng.task_verify(Role.ENGINEERING_LEAD, tid)
    eng.task_submit_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    for story in ["US-004", "US-005", "US-006", "US-007"]:
        complete_task(eng, story)

    assert eng.gate(GateId.INDEPENDENT_REVIEW).status == Status.PASSED
    run = eng.run()
    assert run.stage(Stage.BUILD_REVIEW).status == Status.COMPLETED
    assert run.stage(Stage.QUALITY).status == Status.READY


def test_provenance_versions_review_reports(eng):
    complete_task(eng, "US-001")
    complete_task(eng, "US-002")
    tid = task_of(eng, "US-003")["task_id"]
    eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
    eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
    ledger = eng.state()["provenance_ledger"]
    reviews = [r for r in ledger if r["artifact_type"] == "review_report"]
    assert reviews[-1]["outcome"] == "blocked"
    assert len(reviews[-1]["sha256"]) == 64
