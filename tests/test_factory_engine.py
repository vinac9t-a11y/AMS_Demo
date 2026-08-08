"""Engine lifecycle: run creation, state assembly, reset, role checks."""

import pytest

from s7_delivery.factory.engine import Engine
from s7_delivery.factory.models import DemoMode, Role, Stage, Status
from s7_delivery.factory.roles import PermissionError_, allowed, require
from s7_delivery.factory.seed import build_stories


@pytest.fixture()
def engine(tmp_path):
    return Engine.create(DemoMode.SIMULATION, root=tmp_path)


def test_create_seeds_run_and_requirement(engine):
    state = engine.state()
    assert state["run"]["run_id"] == "S7-00001"
    assert state["run"]["mode"] == "simulation"
    assert state["intake"]["requirement"]["request_id"] == "REQ-2026-114"
    assert state["intake"]["requirement"]["provenance"] == "human"


def test_create_records_provenance_and_activity(engine):
    state = engine.state()
    assert len(state["provenance_ledger"]) == 1
    rec = state["provenance_ledger"][0]
    assert rec["artifact_id"] == "REQ-2026-114"
    assert len(rec["sha256"]) == 64
    assert state["activity"], "run creation must be logged"


def test_intake_stage_starts_ready(engine):
    run = engine.run()
    assert run.stage(Stage.INTAKE).status == Status.READY
    assert run.stage(Stage.PLANNING).status == Status.NOT_STARTED


def test_gates_initialised_not_started(engine):
    assert all(g.status == Status.NOT_STARTED for g in engine.gates())
    assert [g.gate_id.value for g in engine.gates()] == ["G0", "G1", "G2", "G3", "G4"]


def test_reset_restores_seed(engine, tmp_path):
    engine.store.write_json({"x": 1}, "planning", "stories.json")
    engine.reset(Role.DELIVERY_LEAD)
    state = engine.state()
    assert state["planning"]["stories"] == []
    assert state["intake"]["requirement"]["request_id"] == "REQ-2026-114"


def test_state_survives_new_engine_instance(engine, tmp_path):
    """Disk is truth: a fresh Engine over the same run dir sees everything."""
    again = Engine(engine.run_id, root=tmp_path)
    assert again.state()["run"]["run_id"] == engine.run_id


# --- roles ------------------------------------------------------------------


def test_only_business_owner_signs_plan():
    assert allowed("sign_off_plan", Role.BUSINESS_OWNER)
    for role in Role:
        if role is not Role.BUSINESS_OWNER:
            assert not allowed("sign_off_plan", role)


def test_reviewer_cannot_develop_and_developer_cannot_review():
    assert not allowed("run_development", Role.INDEPENDENT_REVIEWER)
    assert not allowed("execute_review", Role.ENGINEERING_LEAD)


def test_release_approval_split():
    """Each required role records its own approval; only the Release
    Manager holds the final, blocking deploy decision."""
    for role in (Role.BUSINESS_OWNER, Role.ENGINEERING_LEAD, Role.QA_LEAD,
                 Role.RELEASE_MANAGER):
        assert allowed("approve_release", role)
    assert not allowed("approve_release", Role.SUPPORT_LEAD)
    assert not allowed("approve_release", Role.PRODUCT_ANALYST)
    assert allowed("deploy", Role.RELEASE_MANAGER)
    for role in Role:
        if role is not Role.RELEASE_MANAGER:
            assert not allowed("deploy", role)


def test_require_raises_for_forbidden(engine):
    with pytest.raises(PermissionError_):
        require("sign_off_plan", Role.ENGINEERING_LEAD)


def test_unknown_action_raises():
    with pytest.raises(PermissionError_):
        require("frobnicate", Role.DELIVERY_LEAD)


# --- seed integrity ---------------------------------------------------------


def test_seed_stories_complete():
    stories = build_stories()
    assert len(stories) == 7
    for story in stories:
        assert story.completeness_gaps() == [], f"{story.story_id}: {story.completeness_gaps()}"


def test_seed_dependencies_resolve():
    stories = build_stories()
    ids = {s.story_id for s in stories}
    for story in stories:
        for dep in story.dependencies:
            assert dep in ids, f"{story.story_id} depends on unknown {dep}"


def test_seed_ac_ids_unique():
    stories = build_stories()
    acs = [ac.ac_id for s in stories for ac in s.acceptance_criteria]
    assert len(acs) == len(set(acs))


def test_defect_target_criterion_present():
    """US-003-AC3 is the deliberate review defect's target — it must exist."""
    stories = {s.story_id: s for s in build_stories()}
    ac_ids = [ac.ac_id for ac in stories["US-003"].acceptance_criteria]
    assert "US-003-AC3" in ac_ids
