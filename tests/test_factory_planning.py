"""Intake → planning flow: gate ordering, plan lock, edit rules."""

import pytest

from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, GateId, Role, Stage, Status
from s7_delivery.factory.roles import PermissionError_


@pytest.fixture()
def eng(tmp_path):
    return Engine.create(DemoMode.SIMULATION, root=tmp_path)


def run_intake(eng):
    eng.intake_analyse(Role.PRODUCT_ANALYST)
    eng.intake_create_epic(Role.PRODUCT_ANALYST)
    eng.intake_pass_gate(Role.DELIVERY_LEAD)


def run_planning(eng):
    run_intake(eng)
    eng.planning_generate(Role.DELIVERY_LEAD)


# --- intake -----------------------------------------------------------------


def test_epic_requires_analysis(eng):
    with pytest.raises(EngineError):
        eng.intake_create_epic(Role.PRODUCT_ANALYST)


def test_intake_gate_blocks_without_epic(eng):
    eng.intake_analyse(Role.PRODUCT_ANALYST)
    with pytest.raises(EngineError, match="Epic created"):
        eng.intake_pass_gate(Role.DELIVERY_LEAD)
    assert eng.gate(GateId.INTAKE).status == Status.BLOCKED


def test_intake_gate_passes_and_opens_planning(eng):
    run_intake(eng)
    assert eng.gate(GateId.INTAKE).status == Status.PASSED
    run = eng.run()
    assert run.stage(Stage.INTAKE).status == Status.COMPLETED
    assert run.stage(Stage.PLANNING).status == Status.READY


def test_intake_role_checks(eng):
    with pytest.raises(PermissionError_):
        eng.intake_analyse(Role.INDEPENDENT_REVIEWER)


# --- planning ---------------------------------------------------------------


def test_planning_requires_intake_gate(eng):
    with pytest.raises(EngineError, match="intake gate"):
        eng.planning_generate(Role.DELIVERY_LEAD)


def test_planning_generates_seven_stories(eng):
    run_planning(eng)
    stories = eng.state()["planning"]["stories"]
    assert [s["story_id"] for s in stories] == [
        "US-001", "US-002", "US-003", "US-004", "US-005", "US-006", "US-007",
    ]


def test_edit_story_bumps_version_and_records_provenance(eng):
    run_planning(eng)
    eng.edit_story(Role.ENGINEERING_LEAD, "US-004", {"estimate": 8})
    state = eng.state()
    story = next(s for s in state["planning"]["stories"] if s["story_id"] == "US-004")
    assert story["estimate"] == 8
    assert story["version"] == 2
    recs = [r for r in state["provenance_ledger"] if r["artifact_id"] == "US-004"]
    assert recs[-1]["version"] == 2
    assert recs[-1]["previous_version"] == 1


def test_edit_story_rejects_non_editable_fields(eng):
    run_planning(eng)
    with pytest.raises(EngineError, match="not editable"):
        eng.edit_story(Role.ENGINEERING_LEAD, "US-004", {"story_id": "US-999"})


def test_sign_off_requires_business_owner(eng):
    run_planning(eng)
    with pytest.raises(PermissionError_):
        eng.planning_sign_off(Role.ENGINEERING_LEAD, "P. Moreau")


def test_sign_off_requires_named_approver(eng):
    run_planning(eng)
    with pytest.raises(EngineError, match="Named approver"):
        eng.planning_sign_off(Role.BUSINESS_OWNER, "  ")
    assert eng.gate(GateId.PLAN_SIGNOFF).status == Status.BLOCKED


def test_sign_off_locks_plan_and_creates_contract(eng):
    run_planning(eng)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau", "Approved for build")
    state = eng.state()
    assert state["run"]["plan_locked"] is True
    assert state["run"]["plan_version"] == 1
    assert state["planning"]["plan"]["signed_by"] == "P. Moreau"
    assert eng.store.exists("planning", "plan.md")
    assert eng.gate(GateId.PLAN_SIGNOFF).status == Status.PASSED
    approvals = state["approvals"]
    assert approvals and approvals[-1]["subject"] == "plan"


def test_locked_plan_rejects_edits(eng):
    run_planning(eng)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    with pytest.raises(EngineError, match="locked"):
        eng.edit_story(Role.ENGINEERING_LEAD, "US-004", {"estimate": 13})
    with pytest.raises(EngineError, match="locked"):
        eng.planning_generate(Role.DELIVERY_LEAD)


def test_sign_off_seeds_work_queue(eng):
    run_planning(eng)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    tasks = eng.state()["build"]["tasks"]
    assert len(tasks) == 7
    us1 = next(t for t in tasks if t["story_id"] == "US-001")
    assert us1["status"] == "ready"          # no dependencies
    us3 = next(t for t in tasks if t["story_id"] == "US-003")
    assert us3["status"] == "not_started"    # waits on US-002


def test_sign_off_opens_build_stage(eng):
    run_planning(eng)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    run = eng.run()
    assert run.stage(Stage.PLANNING).status == Status.COMPLETED
    assert run.stage(Stage.BUILD_REVIEW).status == Status.READY
