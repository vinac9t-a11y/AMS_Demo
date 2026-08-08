"""Per-assignee workspace bundles: assembly, permissions, path safety.

The handoff CLAUDE.md § Design review (item 1) calls for — "a file at a
deterministic path, validated against a schema" — implemented as
`Engine.generate_workspace`. These tests cover the assembly rules in
`s7_delivery.factory.workspace` and the engine/role wiring around it.
"""

import pytest

from s7_delivery.factory import workspace
from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, Role
from s7_delivery.factory.roles import PermissionError_, allowed
from s7_delivery.factory.store import StoreError


@pytest.fixture()
def eng(tmp_path):
    e = Engine.create(DemoMode.SIMULATION, root=tmp_path)
    e.intake_analyse(Role.PRODUCT_ANALYST)
    e.intake_create_epic(Role.PRODUCT_ANALYST)
    e.intake_pass_gate(Role.DELIVERY_LEAD)
    e.planning_generate(Role.DELIVERY_LEAD)
    return e


def signed(eng):
    eng.planning_sign_off(Role.BUSINESS_OWNER, "P. Moreau")
    return eng


def task_of(eng, story_id):
    return next(t for t in eng.state()["build"]["tasks"] if t["story_id"] == story_id)


# --- workspace.py: pure assembly --------------------------------------------


def test_slugify_handles_spaces_and_punctuation():
    assert workspace.slugify("A. Ng") == "a-ng"
    assert workspace.slugify("Priya N.") == "priya-n"


def test_slugify_never_empty():
    assert workspace.slugify("") == "unassigned"
    assert workspace.slugify("   ") == "unassigned"


def test_slugify_forces_alnum_start():
    slug = workspace.slugify("---not-alnum")
    assert slug[0].isalnum()


def test_slugify_rejects_path_traversal_shape():
    """A hostile-looking name still yields a single safe path segment."""
    slug = workspace.slugify("../../etc/passwd")
    assert "/" not in slug
    assert ".." not in slug


def test_assignees_empty_before_ownership_set():
    assert workspace.assignees([{"owner": ""}], [{"owner": ""}]) == []


def test_assignees_dedupes_and_sorts():
    stories = [{"owner": "B. Lee"}, {"owner": "A. Ng"}]
    tasks = [{"owner": "A. Ng"}, {"owner": ""}]
    assert workspace.assignees(stories, tasks) == ["A. Ng", "B. Lee"]


# --- engine wiring -----------------------------------------------------------


def test_generate_workspace_requires_a_name(eng):
    with pytest.raises(EngineError, match="required"):
        eng.generate_workspace(Role.DELIVERY_LEAD, "  ")


def test_generate_workspace_for_unassigned_person_is_empty(eng):
    pkg = eng.generate_workspace(Role.DELIVERY_LEAD, "Nobody Yet")
    assert pkg["stories"] == []
    assert pkg["tasks"] == []
    assert pkg["provenance"] == "simulated"


def test_generate_workspace_filters_by_story_owner(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    pkg = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    assert [s["story_id"] for s in pkg["stories"]] == ["US-001"]


def test_tasks_inherit_story_owner(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    signed(eng)  # locks the plan and seeds tasks
    pkg = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    task_ids = {t["task_id"] for t in pkg["tasks"]}
    assert task_of(eng, "US-001")["task_id"] in task_ids


def test_explicit_task_assignment_overrides_story_owner(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    signed(eng)
    tid = task_of(eng, "US-001")["task_id"]
    eng.assign_task(Role.ENGINEERING_LEAD, tid, "B. Lee")

    pkg_ng = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    pkg_lee = eng.generate_workspace(Role.DELIVERY_LEAD, "B. Lee")
    assert tid not in {t["task_id"] for t in pkg_ng["tasks"]}
    assert tid in {t["task_id"] for t in pkg_lee["tasks"]}
    # The story itself stays with its planning-time owner.
    assert pkg_ng["stories"][0]["story_id"] == "US-001"


def test_blocked_dependency_is_surfaced(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-002", {"owner": "A. Ng"})
    eng.edit_story(Role.DELIVERY_LEAD, "US-003", {"owner": "A. Ng"})
    signed(eng)
    pkg = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    # US-003 depends on US-002, which has not passed yet.
    assert any("US-003" in b for b in pkg["blocked"])


def test_generate_workspace_writes_json_and_markdown(eng, tmp_path):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    on_disk = eng.read_workspace("A. Ng")
    assert on_disk["assignee"] == "A. Ng"
    md = eng.read_workspace_markdown("A. Ng")
    assert "US-001" in md
    assert "A. Ng" in md


def test_regenerating_workspace_bumps_version(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    first = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    second = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    assert second["version"] == first["version"] + 1


def test_generate_workspace_records_provenance(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    ledger = eng.store.read_ledger("provenance.jsonl")
    rec = next(r for r in ledger if r["artifact_type"] == "workspace")
    assert rec["author"] == Role.DELIVERY_LEAD.value
    assert len(rec["sha256"]) == 64


def test_read_workspace_missing_raises_store_error(eng):
    with pytest.raises(StoreError):
        eng.read_workspace("Nobody")


def test_assignees_reflects_current_ownership(eng):
    assert eng.assignees() == []
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    assert eng.assignees() == ["A. Ng"]


# --- permissions --------------------------------------------------------------


def test_any_role_may_generate_a_workspace():
    for role in Role:
        assert allowed("generate_workspace", role)


def test_only_leads_may_assign_a_task():
    assert allowed("assign_task", Role.ENGINEERING_LEAD)
    assert allowed("assign_task", Role.DELIVERY_LEAD)
    assert not allowed("assign_task", Role.INDEPENDENT_REVIEWER)
    assert not allowed("assign_task", Role.BUSINESS_OWNER)


def test_assign_task_enforces_role(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    signed(eng)
    tid = task_of(eng, "US-001")["task_id"]
    with pytest.raises(PermissionError_):
        eng.assign_task(Role.INDEPENDENT_REVIEWER, tid, "A. Ng")


def test_assign_task_requires_a_name(eng):
    signed(eng)
    tid = task_of(eng, "US-001")["task_id"]
    with pytest.raises(EngineError, match="required"):
        eng.assign_task(Role.ENGINEERING_LEAD, tid, "  ")


def test_task_start_preserves_explicit_assignment(eng):
    signed(eng)
    tid = task_of(eng, "US-001")["task_id"]
    eng.assign_task(Role.ENGINEERING_LEAD, tid, "A. Ng")
    eng.task_start(Role.ENGINEERING_LEAD, tid)
    assert task_of(eng, "US-001")["owner"] == "A. Ng"


def test_task_start_falls_back_to_simulated_placeholder(eng):
    signed(eng)
    tid = task_of(eng, "US-001")["task_id"]
    eng.task_start(Role.ENGINEERING_LEAD, tid)
    assert task_of(eng, "US-001")["owner"] == "delivery-worker (simulated)"


# --- markdown rendering -------------------------------------------------------


def test_markdown_render_flags_blocked_and_lists_acceptance_criteria(eng):
    eng.edit_story(Role.DELIVERY_LEAD, "US-001", {"owner": "A. Ng"})
    pkg_dict = eng.generate_workspace(Role.DELIVERY_LEAD, "A. Ng")
    from s7_delivery.factory.models import WorkspacePackage

    pkg = WorkspacePackage.model_validate(pkg_dict)
    md = workspace.render_markdown(pkg)
    assert "## Stories" in md
    assert "US-001" in md
    assert "Acceptance criteria" in md
