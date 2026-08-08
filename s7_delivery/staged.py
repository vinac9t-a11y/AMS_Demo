"""Staged artifacts for EPIC-S7-001.

**Everything in this module is `Provenance.STAGED`** — hand-written ahead of
time, not model output. It exists because LLM access is still an open blocker
(CLAUDE.md § LLM access), and the console needs something real to render before
that is settled.

CLAUDE.md permits staging *only* when the artifact is labelled as staged
wherever it is shown. The provenance field on every object below is what makes
that label travel: the API serialises it and the console renders it as a loud
badge. Do not add an artifact here without `Provenance.STAGED` on it.

Sprint 3 replaces this module with real `common.llm` calls and committed
recordings, flipping provenance to `REPLAYED_AI`. The console does not change
when that happens — that is the point of routing everything through
`s7_delivery/models.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from s7_delivery.models import (
    AcceptanceCriterion,
    AssessedTask,
    Assessment,
    Coverage,
    DesignArtifact,
    Provenance,
    Stream,
    Task,
    UserStory,
)

EPIC_ID = "EPIC-S7-001"


def _task(
    task_id: str,
    story_id: str,
    summary: str,
    stream: Stream,
    coverage: Coverage,
    days: float,
    satisfies: tuple[str, ...],
    *,
    owning_team: str | None = None,
    depends_on: tuple[str, ...] = (),
) -> Task:
    """One decomposed task. Staged like everything else in this module."""
    return Task(
        id=task_id,
        story_id=story_id,
        summary=summary,
        stream=stream,
        coverage=coverage,
        estimate_days=days,
        provenance=Provenance.STAGED,
        satisfies=satisfies,
        depends_on=depends_on,
        owning_team=owning_team,
    )


def assessment() -> Assessment:
    """The epic fanned out across delivery streams.

    The shape of this answer is the deliverable, not the precision of the
    estimates: six tasks across six streams, one of which is a manual change
    another team owns and which three other tasks queue behind.
    """
    tasks = (
        AssessedTask(
            id="T1",
            summary="Sponsor claim submission journey in SponsorConnect",
            stream=Stream.FRONTEND,
            coverage=Coverage.AGENTIC,
            estimate_days=8.0,
            rationale=(
                "Greenfield screens against an API this project also defines. No "
                "legacy component contracts to reverse-engineer, so this generates "
                "and reviews well."
            ),
            depends_on=("T2",),
        ),
        AssessedTask(
            id="T2",
            summary="Submission, upload and status endpoints",
            stream=Stream.API,
            coverage=Coverage.AGENTIC,
            estimate_days=6.0,
            rationale=(
                "Well-bounded CRUD plus document association. The sponsor-scoping "
                "authorization rule is the part that needs careful review, not "
                "generation."
            ),
            depends_on=("T3",),
        ),
        AssessedTask(
            id="T3",
            summary="Submission and document association schema",
            stream=Stream.DATABASE,
            coverage=Coverage.AGENTIC,
            estimate_days=3.0,
            rationale="New tables, no migration of historical paper claims in scope.",
        ),
        AssessedTask(
            id="T4",
            summary="Handoff of completed submissions into intake/indexing",
            stream=Stream.DOCUMENT_INTAKE,
            coverage=Coverage.AI_ASSISTED_EXTERNAL,
            estimate_days=5.0,
            rationale=(
                "AI drafts the integration and its contract tests, but the intake "
                "platform is configured by the document services team. They own the "
                "change window."
            ),
            depends_on=("T2",),
        ),
        AssessedTask(
            id="T5",
            summary="Member lookup field addition on the policy system of record",
            stream=Stream.SYSTEM_OF_RECORD,
            coverage=Coverage.MANUAL,
            estimate_days=10.0,
            rationale=(
                "The business has flagged this system as not modifiable by the "
                "delivery team on this timeline. A manual, externally-owned change "
                "with its own lead time. No AI contribution is claimed."
            ),
            blocked_by_external=True,
        ),
        AssessedTask(
            id="T6",
            summary="Regression suite and integrated test across streams",
            stream=Stream.TEST,
            coverage=Coverage.AGENTIC,
            estimate_days=4.0,
            rationale="Generated from the acceptance criteria, reviewed before it is trusted.",
            depends_on=("T1", "T2", "T4"),
        ),
    )
    return Assessment(
        epic_id=EPIC_ID,
        tasks=tasks,
        integration_note=(
            "Frontend, API and database converge first and can be demonstrated "
            "against a stubbed member lookup. The real convergence point is T5: "
            "pre-population cannot be verified end to end until the system-of-record "
            "field lands, so integrated test and release both sit behind it. "
            "Sequencing the stub deliberately is what stops that dependency from "
            "stalling the other five streams."
        ),
        provenance=Provenance.STAGED,
        generated_at=datetime.now(UTC),
    )


def design() -> tuple[DesignArtifact, ...]:
    """The design step that sits before story breakdown.

    Diagram source is Mermaid text rather than a rendered image: it diffs in
    review, and it needs no rendering toolchain in a locked-down sandbox.
    """
    dfd = DesignArtifact(
        id="DFD-1",
        kind="dfd",
        title="Disability claim submission — data flow",
        source="""flowchart LR
  sponsor([Plan sponsor\\nbenefits administrator])

  subgraph portal[MapleSure SponsorConnect]
    ui[Submission journey UI]
    api[Submission API]
    store[(Submission &\\ndocument store)]
  end

  subgraph external[Outside the delivery team]
    sor[(Policy / member\\nsystem of record)]
    intake[Intake & indexing]
  end

  sponsor -->|policy no. + member id| ui
  ui -->|lookup| api
  api -->|read member + plan| sor
  sor -.->|pre-populated details| api
  api -.->|details for confirmation| ui
  sponsor -->|claim details + attestation| ui
  sponsor -->|supporting documents| ui
  ui -->|submit| api
  api -->|persist submission + docs| store
  api -->|associated packet| intake
  intake -.->|status updates| api
  api -.->|reference + status| ui
  ui -.->|confirmation of receipt| sponsor
""",
        notes=(
            "The trust boundary sits at the portal edge: a sponsor may only ever "
            "retrieve or submit for a member their own organization sponsors, so "
            "the sponsor-scoping check belongs on the API, not the UI. Dashed "
            "edges are responses. The system of record is read-only to this "
            "project except for the one field addition in T5."
        ),
        provenance=Provenance.STAGED,
    )
    relationships = DesignArtifact(
        id="REL-1",
        kind="relationship",
        title="Core entities and their relationships",
        source="""erDiagram
  PLAN_SPONSOR ||--o{ MEMBER : sponsors
  PLAN_SPONSOR ||--o{ SUBMISSION : submits
  MEMBER ||--o{ SUBMISSION : "is subject of"
  SUBMISSION ||--o{ DOCUMENT : includes
  SUBMISSION ||--|| STATUS : has
  POLICY ||--o{ MEMBER : covers
  PLAN_SPONSOR ||--o{ POLICY : holds
""",
        notes=(
            "A submission belongs to exactly one member and one sponsor, which is "
            "what makes the scoping rule enforceable. Status values are deliberately "
            "not enumerated here — EPIC-S7-001 §10 lists them as unvalidated."
        ),
        provenance=Provenance.STAGED,
    )
    return (dfd, relationships)


def stories() -> tuple[UserStory, ...]:
    """The 2-3 visible stories the epic breaks into after the gate.

    This is the convergence point: from here the work is the same shape the
    S3-style enhancement lane produces, and the downstream does not care which
    mode produced it.
    """
    return (
        UserStory(
            id="S7-001-1",
            title="Identify the member and confirm their details",
            narrative=(
                "As a plan sponsor benefits administrator, I want to identify a member "
                "from the policy number and member id I already hold and see the details "
                "MapleSure holds for them, so that I do not re-key information that has "
                "already been recorded and introduce errors."
            ),
            acceptance=(
                AcceptanceCriterion(
                    "AC1",
                    "Given a valid policy number and member id for a member my "
                    "organization sponsors, the member and plan details held against "
                    "that record are displayed for confirmation.",
                ),
                AcceptanceCriterion(
                    "AC2",
                    "Given a member my organization does not sponsor, no member detail "
                    "is disclosed and the submission cannot proceed.",
                ),
                AcceptanceCriterion(
                    "AC3",
                    "Pre-populated details are presented for explicit confirmation and "
                    "are not treated as attested until I confirm them.",
                ),
            ),
            streams=(Stream.FRONTEND, Stream.API, Stream.SYSTEM_OF_RECORD),
            estimate_points=8,
            provenance=Provenance.STAGED,
            epic_id=EPIC_ID,
            assumptions=(
                "The exact set of pre-populated fields is unvalidated — EPIC-S7-001 §10.",
                "Assumes the T5 system-of-record field addition lands; until it does, "
                "this story is verifiable only against a stubbed lookup.",
            ),
            tasks=(
                _task(
                    "S7-001-1-T1",
                    "S7-001-1",
                    "Member lookup form and confirmation screen",
                    Stream.FRONTEND,
                    Coverage.AGENTIC,
                    2.0,
                    ("AC1", "AC3"),
                ),
                _task(
                    "S7-001-1-T2",
                    "S7-001-1",
                    "Member lookup endpoint keyed on policy number and member id",
                    Stream.API,
                    Coverage.AGENTIC,
                    1.5,
                    ("AC1",),
                ),
                _task(
                    "S7-001-1-T3",
                    "S7-001-1",
                    "Sponsor-scope authorization: refuse members outside the caller's "
                    "organization without disclosing whether they exist",
                    Stream.API,
                    Coverage.AGENTIC,
                    1.0,
                    ("AC2",),
                ),
                _task(
                    "S7-001-1-T4",
                    "S7-001-1",
                    "Expose the member detail fields on the policy record",
                    Stream.SYSTEM_OF_RECORD,
                    Coverage.AI_ASSISTED_EXTERNAL,
                    6.0,
                    ("AC1",),
                    owning_team="system-of-record platform team",
                ),
            ),
        ),
        UserStory(
            id="S7-001-2",
            title="Capture the claim details and attach supporting documents",
            narrative=(
                "As a plan sponsor benefits administrator, I want to enter the disability "
                "claim details and attach the supporting statements in one place, so that "
                "MapleSure receives a complete packet instead of documents that arrive "
                "detached and have to be matched by hand."
            ),
            acceptance=(
                AcceptanceCriterion(
                    "AC1",
                    "Claim details required to open an intake file can be captured "
                    "against the confirmed member.",
                ),
                AcceptanceCriterion(
                    "AC2",
                    "Multiple documents can be attached to a single submission and "
                    "remain associated with it.",
                ),
                AcceptanceCriterion(
                    "AC3",
                    "Attachments are subject to the existing file type and size policy, "
                    "and a rejected file explains why.",
                ),
                AcceptanceCriterion(
                    "AC4",
                    "An in-progress submission survives a dropped session and can be resumed.",
                ),
            ),
            streams=(Stream.FRONTEND, Stream.API, Stream.DATABASE),
            estimate_points=13,
            provenance=Provenance.STAGED,
            epic_id=EPIC_ID,
            assumptions=(
                "Which attachments are mandatory versus optional at submission time is "
                "unvalidated — EPIC-S7-001 §10.",
                "Whether a partial submission may be saved and completed later is "
                "unvalidated; AC4 assumes it may.",
            ),
            tasks=(
                _task(
                    "S7-001-2-T1",
                    "S7-001-2",
                    "Claim detail capture form against the confirmed member",
                    Stream.FRONTEND,
                    Coverage.AGENTIC,
                    2.0,
                    ("AC1",),
                ),
                _task(
                    "S7-001-2-T2",
                    "S7-001-2",
                    "Multi-document upload, held associated with one submission",
                    Stream.FRONTEND,
                    Coverage.AGENTIC,
                    3.0,
                    ("AC2",),
                ),
                _task(
                    "S7-001-2-T3",
                    "S7-001-2",
                    "Enforce the existing file type and size policy, with a rejection "
                    "message that says which rule was hit",
                    Stream.API,
                    Coverage.AGENTIC,
                    1.0,
                    ("AC3",),
                ),
                _task(
                    "S7-001-2-T4",
                    "S7-001-2",
                    "Persist an in-progress submission so a dropped session resumes",
                    Stream.DATABASE,
                    Coverage.AGENTIC,
                    2.0,
                    ("AC4",),
                ),
                _task(
                    "S7-001-2-T5",
                    "S7-001-2",
                    "Confirm the retention schedule for uploaded claim documents and "
                    "record the decision",
                    Stream.DOCUMENT_INTAKE,
                    Coverage.MANUAL,
                    1.0,
                    ("AC3",),
                    owning_team="records management",
                ),
            ),
        ),
        UserStory(
            id="S7-001-3",
            title="Confirm receipt and expose submission status",
            narrative=(
                "As a plan sponsor benefits administrator, I want an immediate reference "
                "for my submission and a way to see where it sits afterwards, so that I "
                "stop phoning the service desk to ask whether it arrived."
            ),
            acceptance=(
                AcceptanceCriterion(
                    "AC1",
                    "On submission I receive an unambiguous confirmation carrying a "
                    "reference I can quote.",
                ),
                AcceptanceCriterion(
                    "AC2",
                    "The submission reaches intake as a single associated packet.",
                ),
                AcceptanceCriterion(
                    "AC3",
                    "I can later see the status of submissions my organization made, "
                    "and only those.",
                ),
                AcceptanceCriterion(
                    "AC4",
                    "Every submission records who submitted it, when, and what was attached.",
                ),
            ),
            streams=(Stream.FRONTEND, Stream.API, Stream.DOCUMENT_INTAKE),
            estimate_points=8,
            provenance=Provenance.STAGED,
            epic_id=EPIC_ID,
            assumptions=(
                "The authoritative status values, and who may see each one, are "
                "unvalidated — EPIC-S7-001 §10.",
            ),
            tasks=(
                _task(
                    "S7-001-3-T1",
                    "S7-001-3",
                    "Submission confirmation carrying a quotable reference",
                    Stream.FRONTEND,
                    Coverage.AGENTIC,
                    1.0,
                    ("AC1",),
                ),
                _task(
                    "S7-001-3-T2",
                    "S7-001-3",
                    "Assemble the packet — claim detail plus attachments — as one unit",
                    Stream.API,
                    Coverage.AGENTIC,
                    1.5,
                    ("AC2",),
                ),
                _task(
                    "S7-001-3-T3",
                    "S7-001-3",
                    "Status list scoped to the caller's organization only",
                    Stream.FRONTEND,
                    Coverage.AGENTIC,
                    2.0,
                    ("AC3",),
                ),
                _task(
                    "S7-001-3-T4",
                    "S7-001-3",
                    "Audit record: who submitted, when, and what was attached",
                    Stream.DATABASE,
                    Coverage.AGENTIC,
                    1.0,
                    ("AC4",),
                ),
                _task(
                    "S7-001-3-T5",
                    "S7-001-3",
                    "Hand the packet to the intake indexing queue",
                    Stream.DOCUMENT_INTAKE,
                    Coverage.AI_ASSISTED_EXTERNAL,
                    3.0,
                    ("AC2",),
                    owning_team="document intake platform",
                    depends_on=("S7-001-3-T2",),
                ),
            ),
        ),
    )
