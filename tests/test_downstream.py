"""Downstream lane orchestration: Developer → Tester → pytest → Reviewer.

`complete` is monkeypatched with canned agent replies; the pytest run over the
generated files is real. What these tests guard is the orchestration — files
land where the console expects, events narrate every agent, and a red test run
or failing review verdict flips `ok` without raising.
"""

import json

from s7_delivery import downstream
from s7_delivery.models import (
    AcceptanceCriterion,
    Coverage,
    Provenance,
    Stream,
    Task,
    UserStory,
)

TASK = Task(
    id="US-2-T1",
    story_id="US-2",
    summary="build the submission page",
    stream=Stream.FRONTEND,
    coverage=Coverage.AGENTIC,
    estimate_days=2.0,
    provenance=Provenance.REPLAYED_AI,
    satisfies=("US-2-AC1",),
)
STORY = UserStory(
    id="US-2",
    title="Guided submission",
    narrative="As a sponsor...",
    acceptance=(AcceptanceCriterion("US-2-AC1", "sponsor can submit the claim form"),),
    streams=(Stream.FRONTEND,),
    estimate_points=3,
    provenance=Provenance.REPLAYED_AI,
    tasks=(TASK,),
)

GOOD_TEST = (
    "from pathlib import Path\n"
    "\n"
    "def test_form_present():\n"
    "    html = (Path(__file__).parent / 'index.html').read_text()\n"
    "    assert 'claim-form' in html\n"
)
BAD_TEST = GOOD_TEST.replace("'claim-form' in html", "'missing-thing' in html")


def _fake_complete(test_content=GOOD_TEST, verdict="pass", recheck_verdict=None):
    """Canned agent replies. `verdict` is the first review; `recheck_verdict`
    (default: same as first) is the re-review after the revision loop."""

    def fake(prompt, **kwargs):
        key = kwargs.get("cache_key", "")
        if "developer" in key:
            return json.dumps(
                {
                    "files": [
                        {
                            "path": "index.html",
                            "content": "<html><form id='claim-form'>"
                            "<input id='policy-number'></form></html>",
                        }
                    ]
                }
            )
        if "tester" in key:
            fixed = "fix" in key
            return json.dumps(
                {"files": [{"path": "test_app.py", "content": GOOD_TEST if fixed else test_content}]}
            )
        v = (recheck_verdict if recheck_verdict is not None else verdict) if "recheck" in key else verdict
        return json.dumps(
            {
                "verdict": v,
                "criteria": [{"id": "US-2-AC1", "met": v == "pass", "note": ""}],
                "notes": [],
            }
        )

    return fake


def test_run_lane_produces_app_events_and_green_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(downstream, "complete", _fake_complete())
    result = downstream.run_lane(STORY, TASK, root=tmp_path)
    assert result.ok
    assert (result.app_dir / "index.html").exists()
    assert result.review["verdict"] == "pass"

    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    agents = {e["agent"] for e in events}
    assert {"developer", "tester", "reviewer", "system"} <= agents
    assert all(
        {"ts", "agent", "action", "artifact", "status"} <= set(e) for e in events
    )
    assert events[-1]["status"] == "done"


def test_run_lane_red_tests_triage_to_tester_fix(tmp_path, monkeypatch):
    """A defective test goes red, the Developer's fix cannot green it, so the
    triage hands the Tester one bounded fix — evidence then decides."""
    monkeypatch.setattr(downstream, "complete", _fake_complete(test_content=BAD_TEST))
    result = downstream.run_lane(STORY, TASK, root=tmp_path)
    assert result.ok
    assert result.revised
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    assert any(e["status"] == "fail" for e in events)
    assert any("defective test" in e["action"] for e in events)


def test_run_lane_failing_review_flips_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downstream, "complete", _fake_complete(verdict="fail", recheck_verdict="fail")
    )
    result = downstream.run_lane(STORY, TASK, root=tmp_path)
    assert not result.ok
    assert result.revised
    assert (tmp_path / "review.json").exists()
    assert (tmp_path / "review_first.json").exists()


def test_run_lane_revision_recovers(tmp_path, monkeypatch):
    """First review fails, the Developer's bounded fix pass satisfies the
    re-review — the lane ends ok and the events narrate the whole loop."""
    monkeypatch.setattr(
        downstream, "complete", _fake_complete(verdict="fail", recheck_verdict="pass")
    )
    result = downstream.run_lane(STORY, TASK, root=tmp_path)
    assert result.ok
    assert result.revised
    events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
    actions = [e["action"] for e in events]
    assert any("revision" in a for a in actions)
    assert events[-1]["status"] == "done"
    first = json.loads((tmp_path / "review_first.json").read_text())
    final = json.loads((tmp_path / "review.json").read_text())
    assert first["verdict"] == "fail"
    assert final["verdict"] == "pass"


def test_sanitize_strips_timing():
    assert downstream._sanitize("6 passed in 0.01s") == "6 passed in N.NNs"


def test_write_files_flattens_paths(tmp_path):
    files = downstream._write_files(
        {"files": [{"path": "../evil/index.html", "content": "x"}]}, tmp_path
    )
    assert files == ["index.html"]
    assert (tmp_path / "index.html").exists()
    assert not (tmp_path.parent / "evil").exists()
