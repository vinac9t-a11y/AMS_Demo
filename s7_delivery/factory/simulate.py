"""Deterministic build/test/review evidence for the demo (spec §9).

Everything produced here is labelled `Provenance.SIMULATED` and rendered with
that badge. The content is fixed per story so the demonstration is exactly
repeatable (hard rule 5: a beat that is adequate five times in five).

The deliberate defect lives in US-003. The acceptance criterion US-003-AC3
reads "first day absent **on or before** the last day worked is rejected".
The first development pass implements the strictly-before check (`<`) — and
generates an equality test that mirrors the same misreading, so the targeted
tests are green while the build violates the criterion. The independent
reviewer verifies against the criterion text, not the tests, and blocks with
one major gap. That is the whole argument for NO PHASE SELF-APPROVES, played
out on one character of code.
"""

from __future__ import annotations

from s7_delivery.factory.models import TestCaseRecord

# Per-story development evidence: files, sizes, coverage, and the
# customer-safe change summary. Deterministic demonstration data.
_DEV: dict[str, dict] = {
    "US-001": {
        "files": ["migrations/014_submission_record.sql", "models/submission.py",
                  "models/audit_event.py"],
        "lines_added": 214, "lines_removed": 9, "coverage": 91,
        "summary": "Additive schema for the submission record, draft "
        "persistence and the append-only audit trail. No existing table "
        "altered; rollback is a reverse migration.",
    },
    "US-002": {
        "files": ["services/member_lookup.py", "services/sponsor_scope.py",
                  "api/routes/lookup.py"],
        "lines_added": 187, "lines_removed": 14, "coverage": 89,
        "summary": "Sponsor-scoped lookup service resolving policy number and "
        "member id to pre-population data. Cross-organization requests return "
        "no data and write an audit event.",
    },
    "US-003": {
        "files": ["portal/claim_journey.js", "services/absence_validation.py",
                  "api/routes/submission.py"],
        "lines_added": 246, "lines_removed": 22, "coverage": 86,
        "summary": "Guided claim journey collecting employment and absence "
        "facts, with absence-date validation before submission.",
    },
    "US-004": {
        "files": ["portal/document_upload.js", "services/file_policy.py"],
        "lines_added": 132, "lines_removed": 6, "coverage": 88,
        "summary": "Multi-document upload attached to the submission record, "
        "enforcing the existing file type and size policy with a clear "
        "refusal reason.",
    },
    "US-005": {
        "files": ["integration/intake_packet.py", "integration/retry_queue.py"],
        "lines_added": 158, "lines_removed": 11, "coverage": 84,
        "summary": "Handoff of the completed submission to intake/indexing as "
        "one associated packet, with retry and surfacing on failure. Receiving "
        "contract agreed with the owning team.",
    },
    "US-006": {
        "files": ["tests/regression_submission.py", "tests/integration_journey.py"],
        "lines_added": 208, "lines_removed": 0, "coverage": 93,
        "summary": "Regression and integration scenarios: sponsor isolation, "
        "both absence-date boundaries, upload policy, end-to-end packet "
        "verification at intake.",
    },
    "US-007": {
        "files": ["deploy/pipeline.yaml", "monitoring/alerts.yaml",
                  "runbook/sponsor-submission.md"],
        "lines_added": 96, "lines_removed": 3, "coverage": 0,
        "summary": "Blue-green deployment behind the sponsor_claim_submission "
        "flag, monitoring alerts, runbook and support handover updates.",
    },
}


def dev_evidence(story_id: str) -> dict:
    return _DEV[story_id]


def tests_for(story: dict, *, corrected: bool = False) -> list[TestCaseRecord]:
    """Red-baseline tests derived from the story's acceptance criteria.

    One test per criterion, `initial_result` failed (test-first). For US-003
    the equality-boundary test exists from the start — but until `corrected`,
    its assertion mirrors the developer's `<` misreading, which is why it
    goes green over a defective build.
    """
    records: list[TestCaseRecord] = []
    for i, ac in enumerate(story["acceptance_criteria"], start=1):
        name = _test_name(story["story_id"], ac["ac_id"], ac["text"])
        records.append(
            TestCaseRecord(
                test_id=f"TEST-{story['story_id'][-3:]}-{i:02d}",
                name=name,
                ac_id=ac["ac_id"],
                initial_result="failed",
                current_result="failed",
                evidence_ref=f"build/test-baselines/{story['story_id']}.json",
            )
        )
    if story["story_id"] == "US-003" and corrected:
        for r in records:
            if r.ac_id == "US-003-AC3":
                r.name = "test_rejects_first_day_absent_on_or_before_last_day_worked"
    return records


def _test_name(story_id: str, ac_id: str, text: str) -> str:
    if ac_id == "US-003-AC2":
        return "test_accepts_first_day_absent_after_last_day_worked"
    if ac_id == "US-003-AC3":
        # The defective first version only checks strictly-before — the name
        # honestly reflects what it asserts, which is how the reviewer spots it.
        return "test_rejects_first_day_absent_before_last_day_worked"
    slug = "".join(c if c.isalnum() else "_" for c in text.lower())[:48].strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"test_{slug}"


def change_summary(story_id: str, *, corrected: bool = False) -> str:
    base = _DEV[story_id]["summary"]
    if story_id != "US-003":
        return base
    if corrected:
        return (
            base + " Correction after independent review: the rejection "
            "boundary now includes the equal case (first day absent on or "
            "before last day worked), and the boundary test asserts it."
        )
    return (
        base + " Submissions with first day absent before the last day "
        "worked are rejected."  # 'before', not 'on or before' — the defect.
    )


def review_findings(story_id: str, *, corrected: bool) -> dict:
    """The independent reviewer's verdict, verified against the criteria."""
    if story_id == "US-003" and not corrected:
        return {
            "result": "blocked",
            "critical_gaps": 0,
            "major_gaps": 1,
            "minor_gaps": 0,
            "findings": [
                {
                    "finding_id": "FND-001",
                    "severity": "major",
                    "ac_id": "US-003-AC3",
                    "summary": "Equality boundary not implemented",
                    "detail": (
                        "US-003-AC3 requires rejection when first day absent "
                        "is on or before the last day worked. The validation "
                        "rejects only the strictly-before case, and the "
                        "boundary test asserts the same misreading — a "
                        "submission dated equal to the last day worked is "
                        "accepted. Criterion not fully implemented."
                    ),
                },
            ],
        }
    return {
        "result": "passed",
        "critical_gaps": 0,
        "major_gaps": 0,
        "minor_gaps": 0,
        "findings": [],
    }
