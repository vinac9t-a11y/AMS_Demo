"""Staleness detection and self-correction (spec §15/§16), and traceability.

The demonstrated sequence: development and review complete → the SME ruling
amends DES-001 → downstream artifacts go stale via the ledger's upstream
pointers → release blocks → self-correction re-validates each artifact as a
new version → staleness clears → release proceeds.
"""

import pytest

from s7_delivery.factory import staleness
from s7_delivery.factory.engine import Engine, EngineError
from s7_delivery.factory.models import DemoMode, GateId, Role, Status
from tests.test_factory_quality_release import approve_release_all, drive_to_quality


@pytest.fixture()
def eng(tmp_path):
    e = Engine.create(DemoMode.SIMULATION, root=tmp_path)
    drive_to_quality(e)
    e.quality_run(Role.QA_LEAD)
    e.quality_decide(Role.QA_LEAD)
    return e


# --- detector unit behaviour ------------------------------------------------


def _rec(event, artifact, version, inputs=(), atype="x"):
    return {"event_id": event, "artifact_id": artifact, "version": version,
            "artifact_type": atype, "action": "a", "inputs": list(inputs)}


def test_detect_direct_staleness():
    ledger = [
        _rec("P1", "A", 1),
        _rec("P2", "B", 1, inputs=["A"]),
        _rec("P3", "A", 2),
    ]
    stale = staleness.detect(ledger)
    assert [s["artifact_id"] for s in stale] == ["B"]


def test_detect_transitive_staleness():
    ledger = [
        _rec("P1", "A", 1),
        _rec("P2", "B", 1, inputs=["A"]),
        _rec("P3", "C", 1, inputs=["B"]),
        _rec("P4", "A", 2),
    ]
    stale = staleness.detect(ledger)
    assert {s["artifact_id"] for s in stale} == {"B", "C"}


def test_new_version_clears_staleness():
    ledger = [
        _rec("P1", "A", 1),
        _rec("P2", "B", 1, inputs=["A"]),
        _rec("P3", "A", 2),
        _rec("P4", "B", 2, inputs=["A"]),
    ]
    assert staleness.detect(ledger) == []


def test_unknown_inputs_ignored():
    ledger = [_rec("P1", "B", 1, inputs=["TASK-001"])]
    assert staleness.detect(ledger) == []


# --- the demonstration sequence ---------------------------------------------


def test_run_starts_with_nothing_stale(eng):
    assert eng.state()["staleness"] == []


def test_upstream_change_marks_downstream_stale(eng):
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    stale_ids = {s["artifact_id"] for s in eng.state()["staleness"]}
    assert "US-003" in stale_ids            # story derives from DES-001
    assert "CHG-003" in stale_ids           # code derives from the story
    assert any(a.startswith("REV-") for a in stale_ids)   # review evidence
    assert "QRPT-001" in stale_ids          # quality report derives from reviews
    assert "DES-001" not in stale_ids       # the changed artifact itself is current


def test_upstream_change_is_versioned_never_overwritten(eng):
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    ledger = eng.state()["provenance_ledger"]
    des = [r for r in ledger if r["artifact_id"] == "DES-001"]
    assert [r["version"] for r in des] == [1, 2]
    assert des[1]["previous_version"] == 1
    assert des[0]["sha256"] != des[1]["sha256"]


def test_upstream_change_creates_amendment(eng):
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    amendments = eng.state()["amendments"]
    assert amendments
    assert amendments[-1]["affected_artifacts"]
    assert "SME ruling" in amendments[-1]["reason"]


def test_release_blocked_while_stale(eng):
    eng.release_request_approval(Role.RELEASE_MANAGER)
    approve_release_all(eng)
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    with pytest.raises(EngineError, match="stale"):
        eng.release_deploy(Role.RELEASE_MANAGER)
    assert eng.gate(GateId.RELEASE).status == Status.BLOCKED


def test_self_correction_clears_staleness_and_unblocks_release(eng):
    eng.release_request_approval(Role.RELEASE_MANAGER)
    approve_release_all(eng)
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    with pytest.raises(EngineError):
        eng.release_deploy(Role.RELEASE_MANAGER)

    eng.run_self_correction(Role.DELIVERY_LEAD)
    assert eng.state()["staleness"] == []
    amendments = eng.state()["amendments"]
    assert amendments[-1]["implementation_status"] == "completed"
    assert amendments[-1]["verification_status"] == "completed"

    eng.release_deploy(Role.RELEASE_MANAGER)
    assert eng.gate(GateId.RELEASE).status == Status.PASSED


def test_self_correction_versions_every_stale_artifact(eng):
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    stale_before = {s["artifact_id"]: s["version"] for s in eng.state()["staleness"]}
    eng.run_self_correction(Role.DELIVERY_LEAD)
    ledger = eng.state()["provenance_ledger"]
    latest = {}
    for rec in ledger:
        latest[rec["artifact_id"]] = rec
    for artifact_id, old_version in stale_before.items():
        assert latest[artifact_id]["version"] == old_version + 1, artifact_id
        assert latest[artifact_id]["action"] == "re-validate"


def test_self_correction_requires_something_stale(eng):
    with pytest.raises(EngineError, match="Nothing is stale"):
        eng.run_self_correction(Role.DELIVERY_LEAD)


def test_upstream_change_cannot_apply_twice(eng):
    eng.trigger_upstream_change(Role.PRODUCT_ANALYST)
    with pytest.raises(EngineError, match="already"):
        eng.trigger_upstream_change(Role.PRODUCT_ANALYST)


# --- traceability -----------------------------------------------------------


def test_traceability_chain_complete_after_release(eng):
    eng.release_request_approval(Role.RELEASE_MANAGER)
    approve_release_all(eng)
    eng.release_deploy(Role.RELEASE_MANAGER)
    eng.release_handover(Role.SUPPORT_LEAD)
    rows = eng.traceability()
    ac3 = next(r for r in rows if r["ac"] == "US-003-AC3")
    assert ac3["requirement"] == "REQ-2026-114"
    assert ac3["design"] == "DES-001"
    assert ac3["story"] == "US-003"
    assert ac3["task"] and ac3["change"] and ac3["pr"]
    assert ac3["tests"], "the boundary criterion carries a test"
    assert ac3["review_result"] == "passed"
    assert ac3["quality"] == "QRPT-001"
    assert ac3["deployment"] == "DEP-001"
    assert ac3["handover"] == "HND-001"


def test_traceability_row_per_criterion(eng):
    rows = eng.traceability()
    stories = eng.state()["planning"]["stories"]
    expected = sum(len(s["acceptance_criteria"]) for s in stories)
    assert len(rows) == expected
