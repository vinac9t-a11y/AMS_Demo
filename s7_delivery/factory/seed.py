"""The seeded demo scenario — EPIC-S7-001 recast into the factory's shapes.

All demonstration data. MapleSure Insurance is a fictional insurer; names are
invented; nothing here is client data (hard rules 1 and 2).

The 7-story decomposition mirrors the Control Centre spec's structure but in
the disability-submission domain this repo is recorded against. The deliberate
independent-review defect lives in US-003 / AC-3: the absence-date rule is
"first day absent must be AFTER last day worked — on-or-before is rejected",
and the first implementation checks `<` where the rule needs `<=`, missing the
equality case. Domain-correct, one-character, and exactly the class of bug a
second pair of eyes exists to catch.
"""

from __future__ import annotations

from s7_delivery.factory.models import (
    AcceptanceCriterion,
    EpicRecord,
    FeatureFlag,
    IntakeAnalysis,
    Provenance,
    Requirement,
    RollbackPlan,
    Scenario,
    Status,
    Story,
)

SCENARIO = Scenario(
    scenario_id="disability-submission",
    title="Online disability claim submission for plan sponsors",
    description=(
        "A plan sponsor submits a member's disability claim through "
        "SponsorConnect: guided journey, pre-population, document uploads, "
        "receipt confirmation, status visibility, and handoff to intake as a "
        "single associated packet. Demonstration data throughout."
    ),
    epic_source="crs/EPIC-S7-001.md",
)

TEAMS = [
    "Portal Team",
    "Services Team",
    "Data Team",
    "Intake Integration Team",
    "QA Automation",
    "Platform Team",
    "Support Team",
]

REQUIREMENT = Requirement(
    request_id="REQ-2026-114",
    title="Online disability claim submission for plan sponsors",
    business_owner="Group Benefits Operations",
    domain="Group Disability",
    priority="High",
    requested_date="2026-07-28",
    target_release="2026.R4",
    description=(
        "Give plan sponsors a guided online way to submit a disability claim "
        "for a member through SponsorConnect, and let them see that it arrived "
        "and what is still outstanding. Today the process is fragmented paper "
        "and PDF: forms gathered over email, fax or post, attachments arriving "
        "detached, details re-keyed twice, and no submission visibility "
        "without calling the service desk."
    ),
    source_type="Business requirement document",
    source_documents=["crs/EPIC-S7-001.md"],
    provenance=Provenance.HUMAN,
)

ANALYSIS = IntakeAnalysis(
    problem_understood=True,
    business_impact=(
        "Removes intake rework from incomplete or mismatched packets, cuts "
        "status-chasing service-desk contacts, and creates the first reliable "
        "measure of submission cycle time."
    ),
    affected_applications=[
        "SponsorConnect portal",
        "SponsorConnect API services",
        "Submission data store",
        "Intake/indexing system (externally owned)",
        "Policy/member system of record (externally owned)",
    ],
    stakeholders=[
        "Group Benefits Operations (business owner)",
        "Plan sponsor HR / benefits administrators",
        "Claims intake team",
        "SponsorConnect platform team",
    ],
    dependencies=[
        "Member/plan lookup requires the policy system of record — a field "
        "addition there is externally owned with its own lead time",
        "Intake handoff contract must be agreed with the intake/indexing team",
    ],
    risks=[
        "System-of-record change is not modifiable by this delivery team on "
        "this timeline; sequencing constrained",
        "Status vocabulary unconfirmed — SME validation outstanding",
    ],
    clarification_questions=[
        "Which forms and statements constitute a complete packet?",
        "Which attachments are mandatory versus optional at submission time?",
        "What are the authoritative status values and who may see each one?",
        "Which fields pre-populate from the system of record, and which may be "
        "overridden?",
        "Does an in-progress submission have a retention or expiry period?",
    ],
    assumptions=[
        "Existing SponsorConnect authentication and authorization apply "
        "unchanged",
        "Existing file type and size policy governs uploads",
        "Provisional status set used until SME confirmation",
    ],
    provenance=Provenance.SIMULATED,
)

EPIC = EpicRecord(
    epic_id="EPIC-S7-001",
    title="Online disability claim submission for plan sponsors",
    business_outcome=(
        "A plan sponsor can, unaided, submit a complete disability claim for a "
        "member they sponsor, receive a reference, see its status later, and "
        "intake receives a single associated packet rather than loose "
        "documents."
    ),
    estimated_stories=7,
    status=Status.READY,
    created_by="intake-analysis (simulated)",
    provenance=Provenance.SIMULATED,
)


def _story(**kw) -> Story:
    defaults = dict(
        epic_id="EPIC-S7-001",
        target_application="MapleSure SponsorConnect",
        provenance=Provenance.SIMULATED,
        status=Status.READY,
    )
    defaults.update(kw)
    return Story(**defaults)


def build_stories() -> list[Story]:
    return [
        _story(
            story_id="US-001",
            title="Submission record with draft persistence and audit trail",
            purpose=(
                "Persist the submission as a first-class record so a sponsor's "
                "session drop never loses work, and every submission carries "
                "who submitted, when, and what was attached."
            ),
            accountable_team="Data Team",
            target_component="submission data model",
            target_repository="sponsorconnect-db",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-001-AC1",
                    text="A submission record persists across a dropped sponsor session.",
                ),
                AcceptanceCriterion(
                    ac_id="US-001-AC2",
                    text=(
                        "Every submission carries an append-only audit trail of actor, action and "
                        "time."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-001-AC3",
                    text="Documents are associated to the submission record, never stored loose.",
                ),
            ],
            impacts=["Database schema", "Records retention"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method=(
                    "Feature flag off; schema change is additive and reversible by migration "
                    "rollback."
                )
            ),
            estimate=5,
            sprint=1,
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-002",
            title="Member and plan lookup with sponsor-organization isolation",
            purpose=(
                "Resolve policy number plus member id to pre-population data, "
                "enforcing that a sponsor can never retrieve a member outside "
                "their own organization."
            ),
            accountable_team="Services Team",
            contributing_teams=["Data Team"],
            target_component="lookup service",
            target_repository="sponsorconnect-api",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-002-AC1",
                    text=(
                        "Lookup returns member and plan details for a member the sponsor sponsors."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-002-AC2",
                    text=(
                        "Lookup for a member outside the sponsor organization returns no data and "
                        "is audited."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-002-AC3",
                    text=(
                        "Pre-populated fields are shown for confirmation and attested before "
                        "submission."
                    ),
                ),
            ],
            dependencies=["US-001"],
            impacts=["API services", "System of record (read path, externally owned)"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method="Feature flag off; read-only integration, no data mutation to reverse."
            ),
            estimate=8,
            sprint=1,
            risk="medium",
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-003",
            title="Guided claim journey with absence-date validation",
            purpose=(
                "Collect the structured claim facts intake needs, validating "
                "that the absence dates are coherent before a claim can be "
                "submitted."
            ),
            accountable_team="Portal Team",
            contributing_teams=["Services Team"],
            target_component="claim journey UI + validation service",
            target_repository="sponsorconnect-portal",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-003-AC1",
                    text=(
                        "The journey collects last day worked, first day absent, nature of absence"
                        " and details."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-003-AC2",
                    text="A submission with first day absent after last day worked is accepted.",
                ),
                AcceptanceCriterion(
                    ac_id="US-003-AC3",
                    text=(
                        "A submission where first day absent is on or before the last day worked "
                        "is rejected."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-003-AC4",
                    text=(
                        "Existing SponsorConnect session and authorization behaviour is unchanged."
                    ),
                ),
            ],
            dependencies=["US-002"],
            impacts=["Portal UI", "Validation logic", "Tests"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method="Feature flag off restores the previous journey entry point."
            ),
            estimate=8,
            sprint=2,
            risk="medium",
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-004",
            title="Multi-document upload under the existing file policy",
            purpose=(
                "Attach supporting statements and medical documentation to the "
                "submission, enforcing the existing file type and size policy."
            ),
            accountable_team="Portal Team",
            contributing_teams=["Services Team"],
            target_component="document upload",
            target_repository="sponsorconnect-portal",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-004-AC1",
                    text=(
                        "Multiple documents can be uploaded and are listed against the submission."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-004-AC2",
                    text=(
                        "Files outside the existing type and size policy are refused with a clear "
                        "reason."
                    ),
                ),
            ],
            dependencies=["US-003"],
            impacts=["Portal UI", "Document storage"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method="Feature flag off; uploaded demo documents purged by retention job."
            ),
            estimate=5,
            sprint=2,
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-005",
            title="Intake handoff as a single associated packet",
            purpose=(
                "Deliver the completed submission into the existing "
                "intake/indexing path as one packet — forms and attachments "
                "associated, never loose."
            ),
            accountable_team="Intake Integration Team",
            contributing_teams=["Services Team"],
            target_component="intake handoff",
            target_repository="sponsorconnect-api",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-005-AC1",
                    text="A completed submission reaches intake as a single associated packet.",
                ),
                AcceptanceCriterion(
                    ac_id="US-005-AC2",
                    text=(
                        "Handoff failures are retried and surfaced; a submission is never silently"
                        " dropped."
                    ),
                ),
            ],
            dependencies=["US-001"],
            impacts=["Intake/indexing system (externally owned contract)"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method="Feature flag off; packets already handed off remain valid intake items."
            ),
            estimate=8,
            sprint=2,
            risk="medium",
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-006",
            title="Automated regression and integration scenarios",
            purpose=(
                "Regression and integration coverage across the journey: "
                "sponsor isolation, date validation boundaries, upload policy, "
                "packet handoff."
            ),
            accountable_team="QA Automation",
            target_component="test suites",
            target_repository="sponsorconnect-tests",
            task_type="test",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-006-AC1",
                    text=(
                        "Regression suite covers sponsor isolation and both absence-date "
                        "boundaries."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-006-AC2",
                    text=(
                        "Integration scenario submits end to end and verifies the packet at "
                        "intake."
                    ),
                ),
            ],
            dependencies=["US-002", "US-003", "US-004"],
            impacts=["CI pipeline"],
            rollback_plan=RollbackPlan(
                method="Test-only change; revert commit."
            ),
            estimate=5,
            sprint=2,
            traces_to=["REQ-2026-114"],
        ),
        _story(
            story_id="US-007",
            title="Deployment, monitoring and support handover",
            purpose=(
                "Production deployment behind the feature flag with monitoring, "
                "runbook and support handover updated before release."
            ),
            accountable_team="Platform Team",
            contributing_teams=["Support Team"],
            target_component="deployment + operations",
            target_repository="sponsorconnect-platform",
            task_type="operational",
            acceptance_criteria=[
                AcceptanceCriterion(
                    ac_id="US-007-AC1",
                    text=(
                        "Deployment runs behind the sponsor_claim_submission flag with a validated"
                        " rollback."
                    ),
                ),
                AcceptanceCriterion(
                    ac_id="US-007-AC2",
                    text=(
                        "Monitoring alerts, runbook and support handover are updated and accepted "
                        "by Support."
                    ),
                ),
            ],
            dependencies=["US-001", "US-002", "US-003", "US-004", "US-005", "US-006"],
            impacts=["Monitoring", "Runbook", "Support"],
            feature_flag=FeatureFlag(name="sponsor_claim_submission"),
            rollback_plan=RollbackPlan(
                method=(
                    "Disable flag and restore previous validation route; deployment is blue-green."
                )
            ),
            estimate=5,
            sprint=2,
            traces_to=["REQ-2026-114"],
        ),
    ]
