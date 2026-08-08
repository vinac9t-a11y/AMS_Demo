"""Parsing and model-building for the real generated upstream.

`complete` is monkeypatched throughout — these tests guard the JSON→models
translation, which is the part that breaks under a slightly-off model reply.
Prompt wording is not tested; the recordings are its proof.
"""

import json

import pytest

from s7_delivery import generate
from s7_delivery.models import Coverage, Epic, Provenance, Stream

EPIC = Epic(id="EPIC-S7-001", title="t", body="body text", source_path="x")

ASSESS_FAKE = {
    "tasks": [
        {
            "id": "T1",
            "summary": "submission page",
            "stream": "frontend",
            "coverage": "agentic",
            "estimate_days": 2.0,
            "rationale": "r",
            "depends_on": [],
            "blocked_by_external": False,
        },
        {
            "id": "T2",
            "summary": "system of record field",
            "stream": "system_of_record",
            "coverage": "manual",
            "estimate_days": 5.0,
            "rationale": "externally owned",
            "depends_on": ["T1"],
            "blocked_by_external": True,
        },
    ],
    "integration_note": "note",
}


def test_parse_json_block_strips_fences():
    assert generate.parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert generate.parse_json_block('{"a": 1}') == {"a": 1}
    assert generate.parse_json_block('```\n[1, 2]\n```') == [1, 2]


def test_parse_json_block_bad_json_raises():
    with pytest.raises(json.JSONDecodeError):
        generate.parse_json_block("not json at all")


def test_assessment_builds_models(monkeypatch):
    monkeypatch.setattr(generate, "complete", lambda *a, **k: json.dumps(ASSESS_FAKE))
    a = generate.assessment(EPIC)
    assert a.epic_id == "EPIC-S7-001"
    assert a.tasks[0].stream is Stream.FRONTEND
    assert a.tasks[0].coverage is Coverage.AGENTIC
    assert a.tasks[1].blocked_by_external is True
    assert a.provenance in (Provenance.LIVE_AI, Provenance.REPLAYED_AI)
    assert a.coverage_breakdown()  # effort-weighted, non-empty


def test_design_validates_mermaid(monkeypatch):
    good = {
        "dfd": {"title": "DFD", "mermaid": "flowchart LR\n A --> B", "notes": "n"},
        "er": {"title": "ER", "mermaid": "erDiagram\n A ||--o{ B : has", "notes": "n"},
    }
    monkeypatch.setattr(generate, "complete", lambda *a, **k: json.dumps(good))
    d = generate.design(EPIC, generate_assessment_stub())
    assert [a.kind for a in d] == ["dfd", "er"]

    bad = {
        "dfd": {"title": "DFD", "mermaid": "graph LR", "notes": ""},
        "er": {"title": "ER", "mermaid": "erDiagram", "notes": ""},
    }
    monkeypatch.setattr(generate, "complete", lambda *a, **k: json.dumps(bad))
    with pytest.raises(ValueError, match="DFD"):
        generate.design(EPIC, generate_assessment_stub())


def test_stories_builds_tasks_with_traceability(monkeypatch):
    fake = {
        "stories": [
            {
                "id": "US-1",
                "title": "Submit claim",
                "narrative": "As a sponsor...",
                "acceptance": [{"id": "US-1-AC1", "text": "form submits"}],
                "streams": ["frontend"],
                "estimate_points": 3,
                "assumptions": ["packet contents TBD by SME"],
                "tasks": [
                    {
                        "id": "US-1-T1",
                        "summary": "build submission page",
                        "stream": "frontend",
                        "coverage": "agentic",
                        "estimate_days": 2.0,
                        "satisfies": ["US-1-AC1"],
                        "depends_on": [],
                        "owning_team": None,
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(generate, "complete", lambda *a, **k: json.dumps(fake))
    stories = generate.stories(EPIC, generate_assessment_stub())
    s = stories[0]
    assert s.unsatisfied() == ()
    assert s.tasks[0].story_id == "US-1"
    assert s.tasks[0].runs_in_downstream_lane


def generate_assessment_stub():
    from datetime import datetime

    from s7_delivery.models import AssessedTask, Assessment

    return Assessment(
        epic_id="EPIC-S7-001",
        tasks=(
            AssessedTask(
                id="T1",
                summary="s",
                stream=Stream.FRONTEND,
                coverage=Coverage.AGENTIC,
                estimate_days=1.0,
                rationale="",
            ),
        ),
        integration_note="",
        provenance=Provenance.STAGED,
        generated_at=datetime.now(),
    )
