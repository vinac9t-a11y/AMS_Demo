"""Quality aggregation, quality gate, release approvals, deploy, handover."""

import pytest

from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, GateId, Role, Stage, Status
from s7_delivery.factory.roles import PermissionError_


def drive_to_quality(eng):
    eng.intake_analyse(Role.PRODUCT_ANALYST)
    eng.intake_create_epic(Role.PRODUCT_ANALYST)
    eng.intake_pass_gate(Role.DELIVERY_LEAD)
    eng.planning_generate(Role.DELIVERY_LEAD)
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    order = ["US-001", "US-002", "US-003", "US-004", "US-005", "US-006", "US-007"]
    for story in order:
        tid = next(t for t in eng.state()["build"]["tasks"]
                   if t["story_id"] == story)["task_id"]
        eng.task_run_to_review(Role.ENGINEERING_LEAD, tid)
        report = eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)
        if report["result"] == "blocked":
            eng.review_return_to_development(Role.INDEPENDENT_REVIEWER, tid)
            eng.task_generate_tests(Role.ENGINEERING_LEAD, tid)
            eng.task_develop(Role.ENGINEERING_LEAD, tid)
            eng.task_verify(Role.ENGINEERING_LEAD, tid)
            eng.task_submit_review(Role.ENGINEERING_LEAD, tid)
            eng.review_execute(Role.INDEPENDENT_REVIEWER, tid)


def approve_release_all(eng):
    eng.release_approve(Role.BUSINESS_OWNER, "P. Moreau")
    eng.release_approve(Role.ENGINEERING_LEAD, "A. Osei")
    eng.release_approve(Role.QA_LEAD, "R. Tanaka")
    eng.release_approve(Role.RELEASE_MANAGER, "S. Lindqvist")


@pytest.fixture()
def eng(tmp_path):
    e = Engine.create(DemoMode.SIMULATION, root=tmp_path)
    drive_to_quality(e)
    return e


# --- quality ----------------------------------------------------------------


def test_quality_requires_g2(tmp_path):
    e = Engine.create(DemoMode.SIMULATION, root=tmp_path)
    with pytest.raises(EngineError, match="G2"):
        e.quality_run(Role.QA_LEAD)


def test_quality_checks_computed_from_evidence(eng):
    eng.quality_run(Role.QA_LEAD)
    report = eng.state()["quality"]
    checks = {c["check_id"]: c for c in report["checks"]}
    assert checks["QC-02"]["status"] == "passed"      # every AC coded
    assert checks["QC-03"]["status"] == "passed"      # every AC tested
    assert checks["QC-04"]["status"] == "passed"
    assert checks["QC-07"]["status"] == "passed"      # majors resolved
    assert checks["QC-08"]["status"] == "passed"      # US-007 done
    assert checks["QC-12"]["status"] == "not_applicable"
    assert "informational" in report["score_note"].lower()


def test_quality_gate_passes_and_opens_release(eng):
    eng.quality_run(Role.QA_LEAD)
    eng.quality_decide(Role.QA_LEAD)
    assert eng.gate(GateId.QUALITY).status == Status.PASSED
    assert eng.run().stage(Stage.RELEASE).status == Status.READY


def test_quality_decide_is_qa_lead_only(eng):
    eng.quality_run(Role.QA_LEAD)
    with pytest.raises(PermissionError_):
        eng.quality_decide(Role.DELIVERY_LEAD)


def test_quality_gate_blocks_without_report(eng):
    with pytest.raises(EngineError, match="unmet"):
        eng.quality_decide(Role.QA_LEAD)
    assert eng.gate(GateId.QUALITY).status == Status.BLOCKED


# --- release ----------------------------------------------------------------


@pytest.fixture()
def rel(eng):
    eng.quality_run(Role.QA_LEAD)
    eng.quality_decide(Role.QA_LEAD)
    eng.release_request_approval(Role.RELEASE_MANAGER)
    return eng


def test_release_requires_quality_gate(eng):
    with pytest.raises(EngineError, match="G3"):
        eng.release_request_approval(Role.RELEASE_MANAGER)


def test_deploy_blocked_until_all_approvals(rel):
    rel.release_approve(Role.BUSINESS_OWNER, "P. Moreau")
    with pytest.raises(EngineError, match="approvals"):
        rel.release_deploy(Role.RELEASE_MANAGER)
    assert rel.gate(GateId.RELEASE).status == Status.BLOCKED


def test_rejection_blocks_release(rel):
    rel.release_approve(
        Role.BUSINESS_OWNER, "P. Moreau",
        note="Hold until sponsor comms are ready", decision="rejected",
    )
    assert rel.gate(GateId.RELEASE).status == Status.BLOCKED
    assert rel.state()["release"]["status"] == "blocked"


def test_deploy_requires_release_manager(rel):
    approve_release_all(rel)
    with pytest.raises(PermissionError_):
        rel.release_deploy(Role.ENGINEERING_LEAD)


def test_full_release_flow(rel):
    approve_release_all(rel)
    rel.release_deploy(Role.RELEASE_MANAGER)
    state = rel.state()
    assert rel.gate(GateId.RELEASE).status == Status.PASSED
    assert state["release"]["deployment"]["status"] == "completed"
    assert state["release"]["deployment"]["smoke_test_status"].startswith("passed")

    rel.release_handover(Role.SUPPORT_LEAD)
    state = rel.state()
    assert state["release"]["handover"]["accepted_by"] == "support_lead"
    run = rel.run()
    assert run.status == Status.COMPLETED
    assert run.stage(Stage.RELEASE).status == Status.COMPLETED


def test_handover_requires_deployment(rel):
    approve_release_all(rel)
    with pytest.raises(EngineError, match="Deployment"):
        rel.release_handover(Role.SUPPORT_LEAD)


def test_release_artifacts_written(rel):
    approve_release_all(rel)
    rel.release_deploy(Role.RELEASE_MANAGER)
    rel.release_handover(Role.SUPPORT_LEAD)
    for doc in ["deployment-checklist.md", "rollback-plan.md", "runbook.md",
                "support-handover.md"]:
        assert rel.store.exists("release", doc)


def test_approvals_ledger_is_append_only(rel):
    approve_release_all(rel)
    approvals = rel.state()["approvals"]
    release_rows = [a for a in approvals if a["subject"] == "release"]
    assert len(release_rows) == 4
    assert {a["role"] for a in release_rows} == {
        "business_owner", "engineering_lead", "qa_lead", "release_manager",
    }
