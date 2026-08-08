"""Interactive epic intake — clarify, then plan.

The planning half of the S7 story: an epic arrives, the model asks the
clarifying questions a scrum master would ask, the human answers, and after at
most `MAX_CLARIFICATION_ROUNDS` of that the model must produce a delivery plan
— sprints, stories, assignments — that this module validates before anything
renders it.

The rules the client's checklist cares about live here, not in the HTTP layer,
so no endpoint can route around them:

- **Story quality standards.** Every story must carry a testable acceptance
  criterion set, dependencies, a target component, an impacts note, a feature
  flag (or an explicit none), a rollback plan and a task type. A story missing
  one is a validation error, not a rendering gap.
- **Requirement-to-story coverage.** The model must first inventory the epic's
  committed requirements, and every requirement must be claimed by at least one
  story. Coverage is computed here from the ids, never taken from the model's
  own claim about itself.
- **Assignment is by skill, from a fixed roster.** The model proposes a lead
  per story but only from `TEAM`, and only where the member's streams cover the
  story. An invented name or a skills mismatch fails validation.
- **The activity log is measured, not narrated.** Duration and token counts per
  call come from the clock and the provider's usage block.

Question rounds are capped the same way S3's quick chat caps them: past the
cap the prompt forbids further questions, and a model that asks anyway is
treated as a prompt bug (`LLMError`), not a valid response.

Calls go through `common.llm.complete()` like every other model call in the
repo. Live mode is the interactive default — answers are free text, so there
is nothing to replay until a conversation has been rehearsed; `record` a
rehearsed run and the same epic + the same answers replay offline on demo day.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from common.llm import LLMError, complete, parse_json_response
from common.prompt import PromptLayers
from s7_delivery.models import AcceptanceCriterion, Provenance, Stream

MAX_CLARIFICATION_ROUNDS = 2

# The human review loop is capped like the question rounds: feedback is a
# revision request, not an infinite regeneration budget.
MAX_REVISION_ROUNDS = 2

# The estimate scale the plan prompt asks for; human re-estimates obey it too.
POINT_SCALE = (1, 2, 3, 5, 8, 13)


class ReviewError(ValueError):
    """A human review action that breaks the plan's rules. Maps to HTTP 400."""

SAMPLE_EPIC_PATH = Path(__file__).resolve().parent.parent / "crs" / "EPIC-S7-001.md"


@dataclass(frozen=True)
class TeamMember:
    """One person on the synthetic delivery team, with the streams they cover."""

    name: str
    title: str
    streams: tuple[Stream, ...]


# Synthetic roster (hard rules 1 and 2). Assignment routes by stream coverage;
# the model may not invent names beyond this list.
TEAM: tuple[TeamMember, ...] = (
    TeamMember("Ravi Kumar", "Senior API Engineer", (Stream.API, Stream.SYSTEM_OF_RECORD)),
    TeamMember("Tom Becker", "Frontend Engineer", (Stream.FRONTEND,)),
    TeamMember(
        "Sofia Marchetti",
        "Data & Integration Engineer",
        (Stream.DATABASE, Stream.DOCUMENT_INTAKE, Stream.SYSTEM_OF_RECORD),
    ),
    TeamMember("Priya Nair", "QA Engineer", (Stream.TEST,)),
)

TASK_TYPES = ("feature", "config", "migration", "integration", "test")


@dataclass(frozen=True)
class PlanStory:
    """A story meeting the intake's quality bar — see the module docstring."""

    id: str
    title: str
    narrative: str
    acceptance: tuple[AcceptanceCriterion, ...]
    streams: tuple[Stream, ...]
    estimate_points: int
    task_type: str
    target_component: str
    impacts: str
    feature_flag: str | None
    rollback_plan: str
    depends_on: tuple[str, ...]
    satisfies: tuple[str, ...]
    assignee: str
    assumptions: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str


@dataclass(frozen=True)
class SprintPlan:
    id: str
    goal: str
    story_ids: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryPlan:
    requirements: tuple[Requirement, ...]
    assumptions: tuple[str, ...]
    sprints: tuple[SprintPlan, ...]
    stories: tuple[PlanStory, ...]
    provenance: Provenance

    def unmapped_requirements(self) -> tuple[str, ...]:
        """Requirement ids no story claims. Computed, never model-asserted."""
        claimed = {req_id for story in self.stories for req_id in story.satisfies}
        return tuple(r.id for r in self.requirements if r.id not in claimed)

    def points_by_assignee(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for story in self.stories:
            totals[story.assignee] = totals.get(story.assignee, 0) + story.estimate_points
        return totals


@dataclass
class ActivityEntry:
    """One model call, measured. The factory-activity-log beat."""

    beat: str
    at: str
    seconds: float
    input_tokens: int | None
    output_tokens: int | None
    provenance: str


@dataclass
class ReviewEntry:
    """One human decision on the draft plan — who-did-what, timestamped.

    This is the decision-level record the design review asked for: when a
    demo-day question is "who changed that estimate", the answer is a log
    line, not a memory.
    """

    at: str
    action: str  # reassign | points | move | revision | approve
    detail: str
    story_id: str = ""


@dataclass
class IntakeSession:
    """One epic's journey: text in, questions and answers, then a plan.

    The plan arrives as a *draft*. A human shapes it — reassign, re-estimate,
    move between sprints, or send it back with feedback — and then approves
    it by name. Approval locks it: every edit path checks the lock here, so
    no endpoint can mutate an approved plan.
    """

    epic_text: str
    epic_title: str
    transcript: list[dict[str, str]] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    plan: DeliveryPlan | None = None
    activity: list[ActivityEntry] = field(default_factory=list)
    review_log: list[ReviewEntry] = field(default_factory=list)
    revisions_used: int = 0
    approved_by: str = ""
    approved_at: str = ""
    approval_note: str = ""

    @property
    def rounds_used(self) -> int:
        return sum(1 for turn in self.transcript if turn["role"] == "assistant")

    @property
    def plan_status(self) -> str:
        if self.plan is None:
            return "none"
        return "approved" if self.approved_by else "draft"


RULES = (
    "You are an AI delivery assistant for MapleSure Insurance, a fictional "
    "insurer in a tabletop exercise. All data is synthetic. Answer with "
    "structured JSON only, and never invent facts the input does not support."
)

ROLE = (
    "Your role is the intake planning a product manager and scrum master do by "
    "hand today: read an epic for an application that already exists, ask the "
    "few clarifying questions that materially change the plan, and then break "
    "the epic into a sprint plan of small, independently deliverable user "
    "stories with owners. Ask a question only when the answer would change the "
    "breakdown — most epics need one short round, not an interrogation. Where "
    "the epic leaves a question open and the user has not answered it, do NOT "
    "answer it yourself: carry it as an explicit assumption on the story it "
    "affects."
)


def _team_reference() -> str:
    lines = ["The delivery team. Assign each story's lead from this list ONLY:"]
    for member in TEAM:
        streams = ", ".join(s.value for s in member.streams)
        lines.append(f"- {member.name} ({member.title}) — streams: {streams}")
    lines.append(
        "A story's lead must cover at least one of its streams. Spread the "
        "points; nobody should carry more than half the total."
    )
    return "\n".join(lines)


_PLAN_SHAPE = """{
  "needs_clarification": false,
  "requirements": [
    {"id": "R<n>", "text": "<one committed requirement from the epic, in its words>"}
  ],
  "assumptions": ["<planning assumption carried because nobody answered it>"],
  "stories": [
    {
      "id": "S7-INT-<n>, numbered from 1 in delivery order",
      "title": "<short imperative title>",
      "narrative": "As a <actor>, I want <capability>, so that <outcome>",
      "acceptance": [
        {"id": "AC-<n>", "text": "Given <context>, when <action>, then <observable result>"}
      ],
      "streams": ["subset of: frontend, api, database, document_intake, system_of_record, test"],
      "estimate_points": <integer, 1/2/3/5/8/13>,
      "task_type": "feature | config | migration | integration | test",
      "target_component": "<the part of the existing application this lands in>",
      "impacts": "<one line: what existing behaviour or data this touches>",
      "feature_flag": "<flag name to ship dark behind, or null if truly not needed>",
      "rollback_plan": "<one line: how this is backed out if it misbehaves>",
      "depends_on": ["<story ids this cannot start before>"],
      "satisfies": ["<requirement ids this story delivers>"],
      "assignee": "<a team member name, by stream coverage>",
      "assumptions": ["<only what rests on unanswered questions; empty if none>"]
    }
  ],
  "sprints": [
    {"id": "Sprint <n>", "goal": "<one line>", "story_ids": ["<ids in this sprint>"]}
  ]
}"""


def _build_task(session: IntakeSession, *, force_plan: bool) -> str:
    cap_note = ""
    if force_plan:
        cap_note = (
            "\nYou may NOT ask further questions — produce the final plan now, "
            "carrying anything still unclear as an explicit assumption.\n"
        )
    transcript = "\n".join(
        f"{turn['role']}: {turn['text']}" for turn in session.transcript
    )
    return f"""Conversation so far (empty on the first pass):
{transcript or "(nothing yet)"}
{cap_note}
Return JSON in exactly one of these two shapes.

If — and only if — an answer would materially change the plan, ask (2 to 4
short questions, one topic each):
{{"needs_clarification": true, "questions": ["<question>"]}}

Otherwise, the final plan. First inventory the epic's committed requirements
(committed scope only — not what it defers), then break them into 4 to 8
stories across 2 to 3 sprints. Every requirement id must be claimed by at
least one story's "satisfies", and every story needs 2 to 4 acceptance
criteria, each independently testable. JSON exactly matching:
{_PLAN_SHAPE}"""


def _call(session: IntakeSession, *, beat: str, task: str, key_salt: str = "") -> dict:
    layers = PromptLayers(
        rules=RULES,
        role=ROLE,
        ref=f"{_team_reference()}\n\nThe epic, verbatim:\n\n{session.epic_text}",
        task=task,
    )
    key_material = (
        session.epic_text + json.dumps(session.transcript, sort_keys=True) + key_salt
    )
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]

    usage: dict = {}
    t0 = time.monotonic()
    response = complete(
        layers, json_mode=True, cache_key=f"s7_intake:{digest}", usage_out=usage
    )
    session.activity.append(
        ActivityEntry(
            beat=beat,
            at=datetime.now(UTC).strftime("%H:%M:%S"),
            seconds=round(time.monotonic() - t0, 2),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            provenance=_provenance().value,
        )
    )
    return parse_json_response(response, required_keys={"needs_clarification"})


def _provenance() -> Provenance:
    import os

    mode = os.environ.get("LLM_MODE", "replay").lower()
    return Provenance.LIVE_AI if mode in {"live", "record"} else Provenance.REPLAYED_AI


def start_session(epic_text: str, *, epic_title: str = "") -> IntakeSession:
    """Register the epic and run the first pass — questions or a direct plan."""
    text = epic_text.strip()
    if len(text) < 200:
        raise LLMError(
            "That does not look like an epic — a few sentences is not enough "
            "to plan from. Paste the full epic text."
        )
    session = IntakeSession(epic_text=text, epic_title=epic_title or _title_of(text))
    _advance(session, answers=None)
    return session


def submit_answers(session: IntakeSession, answers: list[str]) -> IntakeSession:
    """Record the user's answers and run the next pass."""
    if session.plan is not None:
        raise LLMError("This session already has a plan. Reset to start over.")
    if not session.pending_questions:
        raise LLMError("There are no open questions to answer.")
    _advance(session, answers=answers)
    return session


def skip_to_plan(session: IntakeSession) -> IntakeSession:
    """The presenter's escape hatch: no more questions, plan from here."""
    if session.plan is not None:
        raise LLMError("This session already has a plan. Reset to start over.")
    session.pending_questions = []
    _advance(session, answers=None, force_plan=True)
    return session


def _advance(
    session: IntakeSession, *, answers: list[str] | None, force_plan: bool = False
) -> None:
    if answers is not None:
        joined = "\n".join(
            f"Q: {q}\nA: {a.strip() or '(no answer — make a stated assumption)'}"
            for q, a in zip(session.pending_questions, answers, strict=True)
        )
        session.transcript.append({"role": "user", "text": joined})
        session.pending_questions = []

    force = force_plan or session.rounds_used >= MAX_CLARIFICATION_ROUNDS
    data = _call(
        session, beat="clarify-or-plan", task=_build_task(session, force_plan=force)
    )

    if data["needs_clarification"]:
        if force:
            raise LLMError(
                "The model asked past the question cap — a prompt bug, not a "
                "valid response."
            )
        questions = [str(q).strip() for q in data.get("questions", []) if str(q).strip()]
        if not 1 <= len(questions) <= 4:
            raise LLMError(f"expected 1-4 clarifying questions, got {len(questions)}")
        session.transcript.append(
            {"role": "assistant", "text": "\n".join(questions)}
        )
        session.pending_questions = questions
        return

    session.plan = _parse_plan(data)


def _title_of(epic_text: str) -> str:
    for line in epic_text.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return "Untitled epic"


def _parse_plan(data: dict) -> DeliveryPlan:  # noqa: PLR0912 — one validator, kept together
    provenance = _provenance()

    raw_requirements = data.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise LLMError("plan has no requirement inventory")
    requirements = tuple(
        Requirement(id=str(r["id"]), text=str(r["text"])) for r in raw_requirements
    )
    requirement_ids = {r.id for r in requirements}

    raw_stories = data.get("stories")
    if not isinstance(raw_stories, list) or not 3 <= len(raw_stories) <= 10:
        raise LLMError("expected 3-10 stories in the plan")

    roster = {member.name: member for member in TEAM}
    stories: list[PlanStory] = []
    seen: set[str] = set()
    for raw in raw_stories:
        story_id = str(raw["id"])
        if story_id in seen:
            raise LLMError(f"duplicate story id {story_id}")
        seen.add(story_id)

        acceptance = tuple(
            AcceptanceCriterion(id=str(c["id"]), text=str(c["text"]))
            for c in raw.get("acceptance", [])
        )
        if not acceptance:
            raise LLMError(f"story {story_id} has no acceptance criteria")

        try:
            streams = tuple(Stream(s) for s in raw["streams"])
        except (KeyError, ValueError) as exc:
            raise LLMError(f"story {story_id} has a bad stream list: {exc}") from exc
        if not streams:
            raise LLMError(f"story {story_id} has no streams")

        points = raw.get("estimate_points")
        if not isinstance(points, int) or points < 1:
            raise LLMError(f"story {story_id} needs positive integer points")

        task_type = str(raw.get("task_type", "")).lower()
        if task_type not in TASK_TYPES:
            raise LLMError(f"story {story_id} task_type {task_type!r} not in {TASK_TYPES}")

        target_component = str(raw.get("target_component", "")).strip()
        impacts = str(raw.get("impacts", "")).strip()
        rollback = str(raw.get("rollback_plan", "")).strip()
        if not (target_component and impacts and rollback):
            raise LLMError(
                f"story {story_id} is below the quality bar — target_component, "
                "impacts and rollback_plan are all required"
            )

        flag_raw = raw.get("feature_flag")
        feature_flag = None if flag_raw in (None, "", "null") else str(flag_raw)

        satisfies = tuple(str(x) for x in raw.get("satisfies", []))
        unknown = [x for x in satisfies if x not in requirement_ids]
        if unknown:
            raise LLMError(f"story {story_id} claims unknown requirement(s) {unknown}")

        assignee = str(raw.get("assignee", ""))
        member = roster.get(assignee)
        if member is None:
            raise LLMError(f"story {story_id} assignee {assignee!r} is not on the team")
        if not set(streams) & set(member.streams):
            raise LLMError(
                f"story {story_id} assigned to {assignee}, whose streams cover "
                "none of the story's"
            )

        stories.append(
            PlanStory(
                id=story_id,
                title=str(raw["title"]),
                narrative=str(raw["narrative"]),
                acceptance=acceptance,
                streams=streams,
                estimate_points=points,
                task_type=task_type,
                target_component=target_component,
                impacts=impacts,
                feature_flag=feature_flag,
                rollback_plan=rollback,
                depends_on=tuple(str(x) for x in raw.get("depends_on", [])),
                satisfies=satisfies,
                assignee=assignee,
                assumptions=tuple(str(a) for a in raw.get("assumptions", [])),
                provenance=provenance,
            )
        )

    story_ids = {s.id for s in stories}
    for story in stories:
        unknown_deps = [d for d in story.depends_on if d not in story_ids]
        if unknown_deps:
            raise LLMError(f"story {story.id} depends on unknown stories {unknown_deps}")

    raw_sprints = data.get("sprints")
    if not isinstance(raw_sprints, list) or not raw_sprints:
        raise LLMError("plan has no sprints")
    sprints = tuple(
        SprintPlan(
            id=str(s["id"]),
            goal=str(s.get("goal", "")),
            story_ids=tuple(str(x) for x in s.get("story_ids", [])),
        )
        for s in raw_sprints
    )
    sprinted = [sid for sprint in sprints for sid in sprint.story_ids]
    if sorted(sprinted) != sorted(story_ids):
        raise LLMError(
            "sprints must place every story exactly once — "
            f"planned {sorted(story_ids)}, sprinted {sorted(sprinted)}"
        )

    return DeliveryPlan(
        requirements=requirements,
        assumptions=tuple(str(a) for a in data.get("assumptions", [])),
        sprints=sprints,
        stories=tuple(stories),
        provenance=provenance,
    )


# ---- human review of the draft plan ---------------------------------------
#
# The plan is a draft until a named human approves it. These functions are the
# only mutation paths, they all enforce the same rules the model is held to
# (roster-only, stream coverage, the point scale, every story in exactly one
# sprint), and every action lands in the review log.


def _now() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _require_draft(session: IntakeSession) -> DeliveryPlan:
    if session.plan is None:
        raise ReviewError("There is no plan to review yet.")
    if session.approved_by:
        raise ReviewError(
            f"The plan is approved and locked (by {session.approved_by}). "
            "Reset the session to start over."
        )
    return session.plan


def _find_story(plan: DeliveryPlan, story_id: str) -> PlanStory:
    for story in plan.stories:
        if story.id == story_id:
            return story
    raise ReviewError(f"No story {story_id!r} in the plan.")


def _replace_story(plan: DeliveryPlan, updated: PlanStory) -> DeliveryPlan:
    stories = tuple(updated if s.id == updated.id else s for s in plan.stories)
    return replace(plan, stories=stories)


def reassign_story(session: IntakeSession, story_id: str, assignee: str) -> None:
    """Hand a story's lead to another team member — same rules as the model."""
    plan = _require_draft(session)
    story = _find_story(plan, story_id)
    member = next((m for m in TEAM if m.name == assignee), None)
    if member is None:
        raise ReviewError(f"{assignee!r} is not on the team.")
    if not set(story.streams) & set(member.streams):
        raise ReviewError(
            f"{assignee} covers none of {story_id}'s streams — "
            "assignment is by skill, for humans too."
        )
    if assignee == story.assignee:
        return
    session.plan = _replace_story(plan, replace(story, assignee=assignee))
    session.review_log.append(ReviewEntry(
        at=_now(),
        action="reassign",
        detail=f"{story_id}: {story.assignee} → {assignee}",
        story_id=story_id,
    ))


def set_story_points(session: IntakeSession, story_id: str, points: int) -> None:
    """Re-estimate a story, on the same scale the plan prompt demands."""
    plan = _require_draft(session)
    story = _find_story(plan, story_id)
    if points not in POINT_SCALE:
        raise ReviewError(f"Points must be one of {POINT_SCALE}.")
    if points == story.estimate_points:
        return
    session.plan = _replace_story(plan, replace(story, estimate_points=points))
    session.review_log.append(ReviewEntry(
        at=_now(),
        action="points",
        detail=f"{story_id}: {story.estimate_points} → {points} pts",
        story_id=story_id,
    ))


def move_story(session: IntakeSession, story_id: str, sprint_id: str) -> None:
    """Move a story to another sprint; every story stays in exactly one."""
    plan = _require_draft(session)
    _find_story(plan, story_id)
    if sprint_id not in {s.id for s in plan.sprints}:
        raise ReviewError(f"No sprint {sprint_id!r} in the plan.")
    source = next(s.id for s in plan.sprints if story_id in s.story_ids)
    if source == sprint_id:
        return
    sprints = tuple(
        replace(
            sprint,
            story_ids=(
                tuple(x for x in sprint.story_ids if x != story_id)
                if sprint.id != sprint_id
                else sprint.story_ids + (story_id,)
            ),
        )
        for sprint in plan.sprints
    )
    session.plan = replace(plan, sprints=sprints)
    session.review_log.append(ReviewEntry(
        at=_now(),
        action="move",
        detail=f"{story_id}: {source} → {sprint_id}",
        story_id=story_id,
    ))


def _plan_as_json(plan: DeliveryPlan) -> str:
    """The current draft, serialized back into the prompt's own shape."""
    return json.dumps({
        "requirements": [{"id": r.id, "text": r.text} for r in plan.requirements],
        "assumptions": list(plan.assumptions),
        "stories": [
            {
                "id": s.id,
                "title": s.title,
                "narrative": s.narrative,
                "acceptance": [{"id": c.id, "text": c.text} for c in s.acceptance],
                "streams": [x.value for x in s.streams],
                "estimate_points": s.estimate_points,
                "task_type": s.task_type,
                "target_component": s.target_component,
                "impacts": s.impacts,
                "feature_flag": s.feature_flag,
                "rollback_plan": s.rollback_plan,
                "depends_on": list(s.depends_on),
                "satisfies": list(s.satisfies),
                "assignee": s.assignee,
                "assumptions": list(s.assumptions),
            }
            for s in plan.stories
        ],
        "sprints": [
            {"id": s.id, "goal": s.goal, "story_ids": list(s.story_ids)}
            for s in plan.sprints
        ],
    }, indent=2)


def request_revision(session: IntakeSession, feedback: str) -> None:
    """The human-feedback loop: the reviewer says what is wrong, the model
    revises the plan, and the revision passes the same validator or fails."""
    plan = _require_draft(session)
    feedback = feedback.strip()
    if len(feedback) < 10:
        raise ReviewError(
            "Say what should change — a word is not reviewable feedback."
        )
    if session.revisions_used >= MAX_REVISION_ROUNDS:
        raise ReviewError(
            f"Revision cap reached ({MAX_REVISION_ROUNDS}). Shape the draft by "
            "hand, or approve it, or reset."
        )

    plan_json = _plan_as_json(plan)
    task = f"""The current draft plan, including any adjustments the human reviewer
already made by hand (keep those unless the feedback says otherwise):

{plan_json}

The human reviewer's feedback on this draft:

{feedback}

Revise the plan to address the feedback. Change only what the feedback asks
for or requires; do not regenerate untouched stories. You may NOT ask
questions. Return the complete revised plan as JSON exactly matching:
{_PLAN_SHAPE}"""

    session.transcript.append({"role": "user", "text": f"Plan feedback: {feedback}"})
    data = _call(session, beat="revise-plan", task=task, key_salt=plan_json)
    if data.get("needs_clarification"):
        raise LLMError(
            "The model asked questions during a revision — a prompt bug, not "
            "a valid response."
        )
    session.plan = _parse_plan(data)
    session.revisions_used += 1
    session.review_log.append(ReviewEntry(
        at=_now(),
        action="revision",
        detail=f"Revision {session.revisions_used}: {feedback}",
    ))


def approve_plan(session: IntakeSession, approver: str, note: str = "") -> None:
    """The sign-off. A named human, a timestamp, and a locked plan."""
    _require_draft(session)
    approver = approver.strip()
    if not approver:
        raise ReviewError("Approval needs a name — an anonymous sign-off is not one.")
    session.approved_by = approver
    session.approved_at = _now()
    session.approval_note = note.strip()
    session.review_log.append(ReviewEntry(
        at=session.approved_at,
        action="approve",
        detail=f"Plan approved by {approver}"
        + (f" — {session.approval_note}" if session.approval_note else ""),
    ))
