"""Control Centre HTTP layer: transitions, permissions, demo scenarios.

The engine tests cover the rules; these verify the HTTP translation —
status codes, error surfaces, and that no endpoint is a side door.
"""

import pytest
from fastapi.testclient import TestClient

import s7_delivery.factory.store as store_module
from apps.control.server import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "RUNS_ROOT", tmp_path)
    return TestClient(app)


@pytest.fixture()
def run_id(client):
    res = client.post("/api/runs", json={"mode": "simulation"})
    assert res.status_code == 200
    return res.json()["run"]["run_id"]


def test_scenarios_and_roles_listed(client):
    assert client.get("/api/scenarios").json()[0]["scenario_id"] == "disability-submission"
    roles = client.get("/api/roles").json()
    assert {r["role"] for r in roles} >= {"business_owner", "independent_reviewer"}


def test_live_mode_refused(client):
    res = client.post("/api/runs", json={"mode": "live"})
    assert res.status_code == 400
    assert "live" in res.json()["detail"].lower()


def test_unknown_mode_and_role_are_400(client, run_id):
    assert client.post("/api/runs", json={"mode": "chaos"}).status_code == 400
    res = client.post(f"/api/runs/{run_id}/intake/analyse", json={"role": "wizard"})
    assert res.status_code == 400


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/S7-99999").status_code == 404


def test_forbidden_role_is_403(client, run_id):
    client.post(f"/api/runs/{run_id}/intake/analyse", json={"role": "product_analyst"})
    client.post(f"/api/runs/{run_id}/intake/create-epic", json={"role": "product_analyst"})
    client.post(f"/api/runs/{run_id}/intake/pass-gate", json={"role": "delivery_lead"})
    client.post(f"/api/runs/{run_id}/planning/generate", json={"role": "delivery_lead"})
    res = client.post(
        f"/api/runs/{run_id}/planning/sign-off",
        json={"role": "engineering_lead", "approver": "A. Osei"},
    )
    assert res.status_code == 403
    assert "business_owner" in res.json()["detail"]


def test_invalid_transition_is_409(client, run_id):
    res = client.post(f"/api/runs/{run_id}/planning/generate", json={"role": "delivery_lead"})
    assert res.status_code == 409
    assert "intake gate" in res.json()["detail"]


def test_locked_plan_edit_is_409(client, run_id):
    for path, body in [
        ("/intake/analyse", {"role": "product_analyst"}),
        ("/intake/create-epic", {"role": "product_analyst"}),
        ("/intake/pass-gate", {"role": "delivery_lead"}),
        ("/planning/generate", {"role": "delivery_lead"}),
        ("/planning/sign-off", {"role": "business_owner", "approver": "P. Moreau"}),
    ]:
        assert client.post(f"/api/runs/{run_id}{path}", json=body).status_code == 200
    res = client.patch(
        f"/api/runs/{run_id}/stories/US-004",
        json={"role": "engineering_lead", "patch": {"estimate": 13}},
    )
    assert res.status_code == 409
    assert "locked" in res.json()["detail"]


def test_reset_restores_seed(client, run_id):
    client.post(f"/api/runs/{run_id}/intake/analyse", json={"role": "product_analyst"})
    res = client.post(f"/api/runs/{run_id}/reset", json={"role": "delivery_lead"})
    assert res.status_code == 200
    state = res.json()
    assert state["intake"]["analysis"] is None
    assert state["planning"]["stories"] == []


def test_demo_scenarios_listed(client):
    names = client.get("/api/demo-scenarios").json()
    assert {"happy-path", "review-failure", "staleness",
            "release-rejected", "missing-test-coverage"} <= set(names)


def test_demo_unknown_scenario_409(client):
    assert client.post("/api/demo/nope").status_code == 409


def test_demo_review_failure_state(client):
    state = client.post("/api/demo/review-failure").json()
    reviews = state["build"]["reviews"]
    assert reviews[-1]["result"] == "blocked"
    assert reviews[-1]["findings"][0]["ac_id"] == "US-003-AC3"
    g2 = next(g for g in state["gates"] if g["gate_id"] == "G2")
    assert g2["status"] == "blocked"


def test_demo_happy_path_completes(client):
    state = client.post("/api/demo/happy-path").json()
    assert state["run"]["status"] == "completed"
    assert state["release"]["handover"] is not None
    assert all(g["status"] == "passed" for g in state["gates"])


def test_demo_staleness_blocks_release(client):
    state = client.post("/api/demo/staleness").json()
    assert state["staleness"], "downstream artifacts must be stale"
    g4 = next(g for g in state["gates"] if g["gate_id"] == "G4")
    assert g4["status"] == "blocked"


def test_demo_missing_coverage_blocks_quality(client):
    state = client.post("/api/demo/missing-test-coverage").json()
    g3 = next(g for g in state["gates"] if g["gate_id"] == "G3")
    assert g3["status"] == "blocked"
    qc03 = next(c for c in state["quality"]["checks"] if c["check_id"] == "QC-03")
    assert qc03["status"] == "failed"
    assert "US-004-AC2" in qc03["evidence"]


def test_demo_release_rejected(client):
    state = client.post("/api/demo/release-rejected").json()
    g4 = next(g for g in state["gates"] if g["gate_id"] == "G4")
    assert g4["status"] == "blocked"
    rejection = [a for a in state["approvals"]
                 if a["subject"] == "release" and a["decision"] == "rejected"]
    assert rejection and "sponsor communications" in rejection[0]["note"]
