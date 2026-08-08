"""Run lifecycle and stage actions for the governed factory.

Every mutation goes through an action method that:
1. checks the acting role (`roles.require`),
2. checks gate/stage preconditions (server-side, never the UI),
3. writes artifacts through the store (atomic JSON / append-only ledgers),
4. appends a provenance record (with content hash) and an activity event.

Phase 1 implements the run lifecycle and state assembly; stage actions land
phase by phase behind the same discipline.
"""

from __future__ import annotations

from typing import Any

from s7_delivery.factory import gates, roles, seed
from s7_delivery.factory.models import (
    STAGE_ORDER,
    ActivityEvent,
    Approval,
    DeliveryRun,
    DemoMode,
    GateId,
    GateRecord,
    ProvenanceRecord,
    Role,
    Stage,
    StageState,
    Status,
    now_iso,
)
from s7_delivery.factory.store import RunStore, next_run_id, sha256_of


class EngineError(Exception):
    """A rule violation: bad transition, unmet gate, unknown id."""


GATE_LABELS = {
    GateId.INTAKE: "Intake complete",
    GateId.PLAN_SIGNOFF: "Plan sign-off",
    GateId.INDEPENDENT_REVIEW: "Independent review",
    GateId.QUALITY: "Quality",
    GateId.RELEASE: "Release",
}


_DEPLOY_CHECKLIST = """# Deployment checklist — REL-2026R4-001 (demonstration)

- [x] All gates G0–G3 passed
- [x] Required approvals recorded (business owner, engineering, QA, release)
- [x] Feature flag `sponsor_claim_submission` off at deploy
- [x] Blue-green targets healthy pre-deploy
- [x] Rollback validated in staging
- [x] Monitoring alerts configured
- [x] Support handover prepared
"""

_ROLLBACK_PLAN = """# Rollback plan — REL-2026R4-001 (demonstration)

Method: disable the `sponsor_claim_submission` feature flag, restoring the
previous journey entry point. Database changes are additive; reverse
migration validated in staging. RTO 15 minutes, RPO 0 (no destructive change).
"""

_RUNBOOK = """# Runbook — sponsor claim submission (demonstration)

Alerts: submission error rate, intake-handoff retry depth, lookup latency p95.
First response: check flag state, then the retry queue; escalate to Platform
Team on-call if handoff failures persist beyond one retry cycle.
"""

_HANDOVER_DOC = """# Support handover — REL-2026R4-001 (demonstration)

Support team: MapleSure Application Support (S1–S6 scope).
Hypercare: 7 days. Known limitations: provisional status vocabulary and
partial-submission retention pending SME confirmation.
"""


class Engine:
    """All operations on one run. Stateless between calls — disk is truth."""

    def __init__(self, run_id: str, root=None):
        self.store = RunStore(run_id, root=root)
        self.run_id = self.store.run_id

    # --- lifecycle ----------------------------------------------------------

    @classmethod
    def create(cls, mode: DemoMode = DemoMode.SIMULATION, root=None) -> Engine:
        run_id = next_run_id(root)
        eng = cls(run_id, root=root)
        run = DeliveryRun(
            run_id=run_id,
            scenario_id=seed.SCENARIO.scenario_id,
            mode=mode,
            status=Status.READY,
            stages=[StageState(stage=s) for s in STAGE_ORDER],
        )
        run.stage(Stage.INTAKE).status = Status.READY
        eng.store.write_json(run, "run.json")
        eng.store.write_json(seed.SCENARIO, "scenario.json")
        eng.store.write_json(seed.REQUIREMENT, "intake", "requirement.json")
        eng._gates_init()
        eng._record(
            artifact_id=seed.REQUIREMENT.request_id,
            artifact_type="requirement",
            payload=seed.REQUIREMENT,
            author=seed.REQUIREMENT.business_owner,
            stage=Stage.INTAKE,
            action="seed",
            outcome="created",
        )
        eng._activity(
            stage=Stage.INTAKE,
            actor="system",
            actor_type="service",
            workflow="run-lifecycle",
            outcome="run created",
            details=f"mode={mode.value}",
        )
        return eng

    def run(self) -> DeliveryRun:
        return DeliveryRun.model_validate(self.store.read_json("run.json"))

    def _save_run(self, run: DeliveryRun) -> None:
        self.store.write_json(run, "run.json")

    def reset(self, role: Role) -> None:
        """Restore the run to its seeded state. Ledgers are truncated too:
        a reset is a new rehearsal, not history to preserve (spec §20)."""
        roles.require("manage_run", role)
        import shutil

        root = self.store.root
        if root.exists():
            shutil.rmtree(root)
        run = DeliveryRun(
            run_id=self.run_id,
            scenario_id=seed.SCENARIO.scenario_id,
            mode=DemoMode.SIMULATION,
            status=Status.READY,
            stages=[StageState(stage=s) for s in STAGE_ORDER],
        )
        run.stage(Stage.INTAKE).status = Status.READY
        self.store.write_json(run, "run.json")
        self.store.write_json(seed.SCENARIO, "scenario.json")
        self.store.write_json(seed.REQUIREMENT, "intake", "requirement.json")
        self._gates_init()
        self._activity(
            stage=Stage.INTAKE, actor="system", actor_type="service",
            workflow="run-lifecycle", outcome="run reset to seed",
        )

    # --- gates --------------------------------------------------------------

    def _gates_init(self) -> None:
        gates = [
            GateRecord(gate_id=g, label=GATE_LABELS[g]).model_dump(mode="json")
            for g in GateId
        ]
        self.store.write_json(gates, "gates.json")

    def gates(self) -> list[GateRecord]:
        return [GateRecord.model_validate(g) for g in self.store.read_json("gates.json")]

    def _save_gate(self, gate: GateRecord) -> None:
        gates = self.gates()
        out = [gate if g.gate_id == gate.gate_id else g for g in gates]
        self.store.write_json([g.model_dump(mode="json") for g in out], "gates.json")

    def gate(self, gate_id: GateId) -> GateRecord:
        for g in self.gates():
            if g.gate_id == gate_id:
                return g
        raise EngineError(f"Unknown gate {gate_id}")

    # --- ledger plumbing ----------------------------------------------------

    def _record(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        payload: Any,
        author: str,
        stage: Stage,
        action: str,
        outcome: str,
        inputs: list[str] | None = None,
        version: int = 1,
        previous_version: int | None = None,
    ) -> ProvenanceRecord:
        existing = self.store.read_ledger("provenance.jsonl")
        rec = ProvenanceRecord(
            event_id=f"PRV-{len(existing) + 1:04d}",
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            sha256=sha256_of(payload),
            author=author,
            inputs=inputs or [],
            previous_version=previous_version,
            run_id=self.run_id,
            stage=stage.value,
            action=action,
            outcome=outcome,
        )
        self.store.append(rec, "provenance.jsonl")
        # Staleness is recomputed on every ledger append: a new version of an
        # upstream artifact marks its downstream stale immediately, and a
        # correction (new downstream version) clears itself the same way.
        from s7_delivery.factory import staleness as _staleness

        self.store.write_json(
            _staleness.detect(self.store.read_ledger("provenance.jsonl")),
            "staleness.json",
        )
        return rec

    def _activity(
        self,
        *,
        stage: Stage,
        actor: str,
        actor_type: str,
        workflow: str = "",
        skill: str = "",
        artifact: str = "",
        duration_s: float = 0.0,
        outcome: str = "",
        details: str = "",
    ) -> None:
        self.store.append(
            ActivityEvent(
                run_id=self.run_id,
                stage=stage.value,
                actor=actor,
                actor_type=actor_type,
                workflow=workflow,
                skill=skill,
                artifact=artifact,
                duration_s=duration_s,
                outcome=outcome,
                details=details,
            ),
            "activity.jsonl",
        )

    # --- state assembly -----------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Everything the Control Centre renders, in one payload."""
        run = self.run()
        provenance = self.store.read_ledger("provenance.jsonl")
        activity = self.store.read_ledger("activity.jsonl")
        current = self._latest_versions(provenance)
        stale = self.store.read_json_or([], "staleness.json")
        stale_ids = {s["artifact_id"] for s in stale}
        for row in current:
            row["stale"] = row["artifact_id"] in stale_ids
        return {
            "run": run.model_dump(mode="json"),
            "scenario": self.store.read_json("scenario.json"),
            "gates": [g.model_dump(mode="json") for g in self.gates()],
            "intake": {
                "requirement": self.store.read_json_or(None, "intake", "requirement.json"),
                "analysis": self.store.read_json_or(None, "intake", "analysis.json"),
                "epic": self.store.read_json_or(None, "intake", "epic.json"),
            },
            "planning": {
                "stories": self.store.read_json_or([], "planning", "stories.json"),
                "plan": self.store.read_json_or(None, "planning", "plan.json"),
            },
            "build": {
                "tasks": self.store.read_json_or([], "build", "tasks.json"),
                "reviews": self.store.read_json_or([], "review", "reviews.json"),
            },
            "quality": self.store.read_json_or(None, "quality", "quality-report.json"),
            "release": self.store.read_json_or(None, "release", "release-record.json"),
            "staleness": stale,
            "amendments": self.store.read_ledger("amendments.jsonl"),
            "approvals": self.store.read_ledger("approvals.jsonl"),
            "design": self.store.read_json_or(None, "planning", "design.json"),
            "traceability": self.traceability(),
            "provenance": current,
            "provenance_ledger": provenance,
            "activity": activity,
            "activity_summary": self._activity_summary(activity),
        }

    @staticmethod
    def _latest_versions(provenance: list[dict]) -> list[dict]:
        """Current view of the ledger: one row per artifact, latest version."""
        latest: dict[str, dict] = {}
        for rec in provenance:
            latest[rec["artifact_id"]] = rec
        return sorted(latest.values(), key=lambda r: r["event_id"])

    @staticmethod
    def _activity_summary(activity: list[dict]) -> dict[str, Any]:
        by_outcome = {
            "ai_workflows": 0,
            "human_approvals": 0,
            "artifacts_created": 0,
            "artifacts_amended": 0,
            "gate_failures": 0,
            "gate_retries": 0,
        }
        stage_time: dict[str, float] = {}
        for ev in activity:
            if ev.get("actor_type") == "simulation":
                by_outcome["ai_workflows"] += 1
            if "approval" in ev.get("workflow", ""):
                by_outcome["human_approvals"] += 1
            if ev.get("outcome", "").startswith("created"):
                by_outcome["artifacts_created"] += 1
            if ev.get("outcome", "").startswith("amended"):
                by_outcome["artifacts_amended"] += 1
            if "gate" in ev.get("workflow", "") and ev.get("outcome") == "failed":
                by_outcome["gate_failures"] += 1
            if "gate" in ev.get("workflow", "") and ev.get("outcome") == "retried":
                by_outcome["gate_retries"] += 1
            stage_time[ev.get("stage", "?")] = (
                stage_time.get(ev.get("stage", "?"), 0.0) + float(ev.get("duration_s", 0))
            )
        return {"counters": by_outcome, "stage_time_s": stage_time,
                "total_events": len(activity)}

    # --- stage helpers ------------------------------------------------------

    def _advance_stage(self, run: DeliveryRun, done: Stage) -> None:
        """Mark a stage completed and ready the next one."""
        state = run.stage(done)
        state.status = Status.COMPLETED
        state.completed_at = now_iso()
        idx = STAGE_ORDER.index(done)
        if idx + 1 < len(STAGE_ORDER):
            nxt = run.stage(STAGE_ORDER[idx + 1])
            if nxt.status == Status.NOT_STARTED:
                nxt.status = Status.READY
        self._save_run(run)

    def _stage_in_progress(self, stage: Stage) -> None:
        run = self.run()
        state = run.stage(stage)
        if state.status == Status.NOT_STARTED:
            raise EngineError(
                f"Stage {stage.value} has not been opened by the preceding gate"
            )
        if state.status in (Status.READY, Status.WAITING_INPUT):
            state.status = Status.IN_PROGRESS
            if not state.started_at:
                state.started_at = now_iso()
            self._save_run(run)

    # --- intake (spec §7) ---------------------------------------------------

    def intake_analyse(self, role: Role) -> None:
        roles.require("run_intake_analysis", role)
        self._stage_in_progress(Stage.INTAKE)
        analysis = seed.ANALYSIS.model_copy(update={"generated_at": now_iso()})
        self.store.write_json(analysis, "intake", "analysis.json")
        self._record(
            artifact_id="ANL-001", artifact_type="intake_analysis",
            payload=analysis, author="intake-analysis (simulated)",
            stage=Stage.INTAKE, action="analyse",
            outcome="created", inputs=[seed.REQUIREMENT.request_id],
        )
        self._activity(
            stage=Stage.INTAKE, actor="intake-analysis", actor_type="simulation",
            workflow="intake-analysis", artifact="ANL-001", duration_s=6.0,
            outcome="created", details="requirement analysed; open questions surfaced",
        )

    def intake_create_epic(self, role: Role) -> None:
        roles.require("create_epic", role)
        if not self.store.exists("intake", "analysis.json"):
            raise EngineError("Run intake analysis before creating the epic")
        epic = seed.EPIC.model_copy(update={"created_at": now_iso()})
        self.store.write_json(epic, "intake", "epic.json")
        self._record(
            artifact_id=epic.epic_id, artifact_type="epic", payload=epic,
            author=epic.created_by, stage=Stage.INTAKE, action="create-epic",
            outcome="created", inputs=[seed.REQUIREMENT.request_id, "ANL-001"],
        )
        self._activity(
            stage=Stage.INTAKE, actor="intake-analysis", actor_type="simulation",
            workflow="epic-creation", artifact=epic.epic_id, duration_s=3.0,
            outcome="created",
        )

    def intake_pass_gate(self, role: Role) -> None:
        roles.require("pass_intake_gate", role)
        conditions = gates.intake_gate(
            self.store.read_json_or(None, "intake", "requirement.json"),
            self.store.read_json_or(None, "intake", "analysis.json"),
            self.store.read_json_or(None, "intake", "epic.json"),
        )
        gate = self.gate(GateId.INTAKE)
        gate.conditions = conditions
        if not gates.all_met(conditions):
            gate.status = Status.BLOCKED
            self._save_gate(gate)
            unmet = "; ".join(c["condition"] for c in conditions if not c["met"])
            self._activity(
                stage=Stage.INTAKE, actor=role.value, actor_type="human",
                workflow="intake-gate", outcome="failed", details=unmet,
            )
            raise EngineError(f"Intake gate blocked — unmet: {unmet}")
        gate.status = Status.PASSED
        gate.decided_by = role.value
        gate.decided_at = now_iso()
        self._save_gate(gate)
        run = self.run()
        self._advance_stage(run, Stage.INTAKE)
        self._activity(
            stage=Stage.INTAKE, actor=role.value, actor_type="human",
            workflow="intake-gate", outcome="passed",
        )

    # --- planning (spec §8) -------------------------------------------------

    EDITABLE_STORY_FIELDS = {
        "accountable_team", "owner", "estimate", "sprint", "dependencies",
        "acceptance_criteria", "contributing_teams", "risk",
    }

    def _stories(self) -> list[dict]:
        return self.store.read_json_or([], "planning", "stories.json")

    def planning_generate(self, role: Role) -> None:
        roles.require("generate_plan", role)
        if self.gate(GateId.INTAKE).status != Status.PASSED:
            raise EngineError("Planning opens after the intake gate (G0) passes")
        if self.run().plan_locked:
            raise EngineError("The plan is locked; use an amendment to change it")
        self._stage_in_progress(Stage.PLANNING)

        # The design artifact the stories derive from — the upstream pointer
        # the staleness demonstration flips (spec §15). Its rules quote the
        # epic's provisional answers to the open SME questions.
        design = {
            "design_id": "DES-001",
            "title": "Sponsor submission — design decisions",
            "rules": {
                "absence_dates": (
                    "First day absent must be after the last day worked; a "
                    "submission dated on or before the last day worked is "
                    "rejected (US-003)."
                ),
                "draft_retention": (
                    "PROVISIONAL pending SME: an in-progress submission is "
                    "retained for 30 days before expiry."
                ),
                "packet": (
                    "PROVISIONAL pending SME: employer statement mandatory at "
                    "submission; employee and physician statements may follow."
                ),
            },
            "provenance": "simulated",
            "version": 1,
        }
        self.store.write_json(design, "planning", "design.json")
        self._record(
            artifact_id="DES-001", artifact_type="design", payload=design,
            author="planning (simulated)", stage=Stage.PLANNING,
            action="design", outcome="created",
            inputs=["EPIC-S7-001", "ANL-001"],
        )

        stories = [s.model_dump(mode="json") for s in seed.build_stories()]
        self.store.write_json(stories, "planning", "stories.json")
        for s in stories:
            self._record(
                artifact_id=s["story_id"], artifact_type="story", payload=s,
                author="planning (simulated)", stage=Stage.PLANNING,
                action="decompose", outcome="created",
                inputs=[s["epic_id"], seed.REQUIREMENT.request_id, "DES-001"],
            )
        self._activity(
            stage=Stage.PLANNING, actor="planning", actor_type="simulation",
            workflow="epic-decomposition", duration_s=12.0, outcome="created",
            details=f"{len(stories)} stories across "
            f"{len({s['accountable_team'] for s in stories})} teams",
        )

    def edit_story(self, role: Role, story_id: str, patch: dict) -> None:
        roles.require("edit_story", role)
        if self.run().plan_locked:
            raise EngineError(
                "The signed plan is locked; changes require an amendment"
            )
        stories = self._stories()
        target = next((s for s in stories if s["story_id"] == story_id), None)
        if target is None:
            raise EngineError(f"Unknown story {story_id}")
        illegal = set(patch) - self.EDITABLE_STORY_FIELDS
        if illegal:
            raise EngineError(f"Fields not editable: {', '.join(sorted(illegal))}")
        previous = target["version"]
        target.update(patch)
        target["version"] = previous + 1
        self.store.write_json(stories, "planning", "stories.json")
        self._record(
            artifact_id=story_id, artifact_type="story", payload=target,
            author=role.value, stage=Stage.PLANNING, action="edit",
            outcome=f"amended ({', '.join(sorted(patch))})",
            version=target["version"], previous_version=previous,
        )
        self._activity(
            stage=Stage.PLANNING, actor=role.value, actor_type="human",
            workflow="story-edit", artifact=story_id,
            outcome="amended", details=", ".join(sorted(patch)),
        )

    def planning_revise(self, role: Role, feedback: str) -> None:
        roles.require("request_plan_revision", role)
        if self.run().plan_locked:
            raise EngineError("The signed plan is locked; changes require an amendment")
        if not feedback.strip():
            raise EngineError("Revision feedback is required")
        notes = self.store.read_json_or([], "planning", "revision-notes.json")
        notes.append({"at": now_iso(), "by": role.value, "feedback": feedback.strip()})
        self.store.write_json(notes, "planning", "revision-notes.json")
        self._activity(
            stage=Stage.PLANNING, actor=role.value, actor_type="human",
            workflow="plan-revision", outcome="requested", details=feedback.strip()[:200],
        )

    def planning_sign_off(self, role: Role, approver: str, note: str = "") -> None:
        roles.require("sign_off_plan", role)
        stories = self._stories()
        conditions = gates.plan_signoff_gate(stories, approver)
        gate = self.gate(GateId.PLAN_SIGNOFF)
        gate.conditions = conditions
        if not gates.all_met(conditions):
            gate.status = Status.BLOCKED
            self._save_gate(gate)
            unmet = "; ".join(c["condition"] for c in conditions if not c["met"])
            self._activity(
                stage=Stage.PLANNING, actor=approver or role.value,
                actor_type="human", workflow="plan-signoff-gate",
                outcome="failed", details=unmet,
            )
            raise EngineError(f"Plan sign-off blocked — unmet: {unmet}")

        run = self.run()
        run.plan_locked = True
        run.plan_version += 1
        self._save_run(run)

        plan = {
            "plan_version": run.plan_version,
            "signed_by": approver,
            "signed_at": now_iso(),
            "note": note,
            "story_ids": [s["story_id"] for s in stories],
            "story_versions": {s["story_id"]: s["version"] for s in stories},
        }
        self.store.write_json(plan, "planning", "plan.json")
        self.store.write_text(self._plan_markdown(plan, stories), "planning", "plan.md")

        gate.status = Status.PASSED
        gate.decided_by = approver
        gate.decided_at = now_iso()
        gate.note = note
        self._save_gate(gate)

        approvals = self.store.read_ledger("approvals.jsonl")
        self.store.append(
            Approval(
                approval_id=f"APR-{len(approvals) + 1:03d}",
                subject="plan",
                role=role,
                approver=approver,
                decision="approved",
                note=note,
            ),
            "approvals.jsonl",
        )
        self._record(
            artifact_id="PLAN-001", artifact_type="plan", payload=plan,
            author=approver, stage=Stage.PLANNING, action="sign-off",
            outcome="created", inputs=[s["story_id"] for s in stories],
            version=run.plan_version,
        )
        run = self.run()
        self._advance_stage(run, Stage.PLANNING)
        self._seed_tasks(stories)
        self._activity(
            stage=Stage.PLANNING, actor=approver, actor_type="human",
            workflow="plan-signoff-approval", outcome="passed",
            details=f"plan v{plan['plan_version']} locked; downstream work opened",
        )

    # --- build & independent review (spec §9) ------------------------------

    def _tasks(self) -> list[dict]:
        return self.store.read_json_or([], "build", "tasks.json")

    def _save_tasks(self, tasks: list[dict]) -> None:
        self.store.write_json(tasks, "build", "tasks.json")

    def _task(self, tasks: list[dict], task_id: str) -> dict:
        target = next((t for t in tasks if t["task_id"] == task_id), None)
        if target is None:
            raise EngineError(f"Unknown task {task_id}")
        return target

    def _story(self, story_id: str) -> dict:
        story = next(
            (s for s in self._stories() if s["story_id"] == story_id), None
        )
        if story is None:
            raise EngineError(f"Unknown story {story_id}")
        return story

    def _reviews(self) -> list[dict]:
        return self.store.read_json_or([], "review", "reviews.json")

    def _latest_reviews(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for r in self._reviews():
            latest[r["task_id"]] = r
        return latest

    def _was_blocked(self, task_id: str) -> bool:
        return any(
            r["task_id"] == task_id and r["result"] == "blocked"
            for r in self._reviews()
        )

    def assign_task(self, role: Role, task_id: str, owner: str) -> None:
        """Name who is picking up a task, independent of `task_start`.

        A story's `owner` (edited via `edit_story`) is the planning-time
        assignment; this is the build-time one, and the two can differ — a
        lead may assign the story to a team lead but the task itself to the
        engineer doing the work. `generate_workspace` reads both.
        """
        roles.require("assign_task", role)
        owner = owner.strip()
        if not owner:
            raise EngineError("Assignee name is required")
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        previous_owner = task.get("owner", "")
        task["owner"] = owner
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._record(
            artifact_id=task_id, artifact_type="task", payload=task,
            author=role.value, stage=Stage.BUILD_REVIEW, action="assign",
            outcome=f"assigned to {owner}"
            + (f" (was {previous_owner})" if previous_owner else ""),
            version=task.get("version", 1),
        )
        self._activity(
            stage=Stage.BUILD_REVIEW, actor=role.value, actor_type="human",
            workflow="task-assign", artifact=task_id, outcome="assigned",
            details=owner,
        )

    def task_start(self, role: Role, task_id: str) -> None:
        roles.require("start_task", role)
        if not self.run().plan_locked:
            raise EngineError("Build opens after the plan is signed (G1)")
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task["status"] not in (Status.READY, "ready", Status.IN_PROGRESS, "in_progress"):
            raise EngineError(
                f"{task_id} is {task['status']}; only a ready task can start "
                "(dependencies must be complete)"
            )
        task["status"] = Status.IN_PROGRESS.value
        task["progress_pct"] = 10
        if not task.get("owner"):
            # Preserve an explicit assignment made via `assign_task`; only
            # fall back to the simulated placeholder when nobody was named.
            task["owner"] = "delivery-worker (simulated)"
        task["current_activity"] = (
            "Workspace created; signed plan validated; upstream artifacts "
            "checked for staleness"
        )
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._stage_in_progress(Stage.BUILD_REVIEW)
        self._activity(
            stage=Stage.BUILD_REVIEW, actor="delivery-worker",
            actor_type="simulation", workflow="task-start", artifact=task_id,
            duration_s=2.0, outcome="started", details=task["summary"],
        )

    def task_generate_tests(self, role: Role, task_id: str) -> None:
        roles.require("run_development", role)
        from s7_delivery.factory import simulate

        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task["status"] != Status.IN_PROGRESS.value:
            raise EngineError(f"{task_id} is not in progress")
        story = self._story(task["story_id"])
        corrected = self._was_blocked(task_id)
        tests = [t.model_dump(mode="json")
                 for t in simulate.tests_for(story, corrected=corrected)]
        task["tests"] = tests
        task["progress_pct"] = 35
        task["current_activity"] = (
            "Test scenarios generated from acceptance criteria; red baseline "
            "recorded — every test fails before implementation"
        )
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self.store.write_json(
            {"task_id": task_id, "baseline": "red", "tests": tests},
            "build", "test-baselines", f"{task['story_id']}.json",
        )
        baseline_version = 2 if corrected else 1
        self._record(
            artifact_id=f"TSTB-{task_id[-3:]}", artifact_type="test_baseline",
            payload=tests, author="delivery-worker (simulated)",
            stage=Stage.BUILD_REVIEW, action="generate-tests",
            outcome="amended (corrected baseline)" if corrected
            else "created (red baseline)",
            inputs=[task["story_id"]],
            version=baseline_version,
            previous_version=1 if corrected else None,
        )
        self._activity(
            stage=Stage.BUILD_REVIEW, actor="delivery-worker",
            actor_type="simulation", workflow="test-first", artifact=task_id,
            duration_s=8.0, outcome="created",
            details=f"{len(tests)} tests, all initially failing",
        )

    def task_develop(self, role: Role, task_id: str) -> None:
        roles.require("run_development", role)
        from s7_delivery.factory import simulate

        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if not task.get("tests"):
            raise EngineError(
                f"{task_id} has no red test baseline; generate tests first "
                "(test-first is the demonstrated workflow)"
            )
        corrected = self._was_blocked(task_id)
        ev = simulate.dev_evidence(task["story_id"])
        previous = task["version"]
        task["files_changed"] = len(ev["files"])
        task["changed_files"] = ev["files"]
        task["lines_added"] = ev["lines_added"]
        task["lines_removed"] = ev["lines_removed"]
        task["coverage_pct"] = ev["coverage"]
        task["change_summary"] = simulate.change_summary(
            task["story_id"], corrected=corrected
        )
        task["commit_ref"] = f"c{abs(hash((task_id, corrected))) % 10**7:07d}"
        task["pr_ref"] = f"PR-{int(task_id[-3:]) + 20}"
        if corrected:
            task["version"] = previous + 1
            task["tests"] = [
                t.model_dump(mode="json")
                for t in simulate.tests_for(self._story(task["story_id"]), corrected=True)
            ]
        for t in task["tests"]:
            t["current_result"] = "passed"
        task["progress_pct"] = 80
        task["current_activity"] = (
            "Correction applied per independent review; targeted tests green"
            if corrected
            else "Smallest compliant change implemented; targeted tests green"
        )
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._record(
            artifact_id=f"CHG-{task_id[-3:]}", artifact_type="code_change",
            payload={"files": ev["files"], "summary": task["change_summary"]},
            author="delivery-worker (simulated)", stage=Stage.BUILD_REVIEW,
            action="correct" if corrected else "develop",
            outcome="amended" if corrected else "created",
            inputs=[task["story_id"], f"TSTB-{task_id[-3:]}"],
            version=task["version"],
            previous_version=previous if corrected else None,
        )
        self._activity(
            stage=Stage.BUILD_REVIEW, actor="delivery-worker",
            actor_type="simulation", workflow="development", artifact=task_id,
            duration_s=45.0, outcome="amended" if corrected else "created",
            details=task["change_summary"][:160],
        )

    def task_verify(self, role: Role, task_id: str) -> None:
        roles.require("run_development", role)
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if not task.get("files_changed"):
            raise EngineError(f"{task_id} has no implementation to verify")
        task["progress_pct"] = 90
        task["current_activity"] = (
            "Developer verification complete: build valid, targeted tests "
            "green, change summary produced"
        )
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._activity(
            stage=Stage.BUILD_REVIEW, actor="delivery-worker",
            actor_type="simulation", workflow="developer-verification",
            artifact=task_id, duration_s=6.0, outcome="passed",
        )

    def task_submit_review(self, role: Role, task_id: str) -> None:
        roles.require("submit_for_review", role)
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task.get("progress_pct", 0) < 90:
            raise EngineError(
                f"{task_id} has not completed developer verification"
            )
        task["status"] = Status.WAITING_APPROVAL.value
        task["current_activity"] = "Evidence submitted for independent review"
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._activity(
            stage=Stage.BUILD_REVIEW, actor=role.value, actor_type="human",
            workflow="submit-review", artifact=task_id, outcome="submitted",
        )

    def task_run_to_review(self, role: Role, task_id: str) -> None:
        """Convenience for the demo: start → tests → develop → verify →
        submit, each step logged individually. The reviewer is still a
        separate role and a separate action — this never reviews."""
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task["status"] in (Status.READY.value, Status.BLOCKED.value):
            if task["status"] == Status.BLOCKED.value:
                raise EngineError(
                    f"{task_id} is blocked by review; return it to "
                    "development first"
                )
            self.task_start(role, task_id)
        self.task_generate_tests(role, task_id)
        self.task_develop(role, task_id)
        self.task_verify(role, task_id)
        self.task_submit_review(role, task_id)

    # --- independent review -------------------------------------------------

    def review_execute(self, role: Role, task_id: str) -> dict:
        roles.require("execute_review", role)
        from s7_delivery.factory import simulate

        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task["status"] != Status.WAITING_APPROVAL.value:
            raise EngineError(f"{task_id} has not been submitted for review")
        corrected = self._was_blocked(task_id)
        verdict = simulate.review_findings(task["story_id"], corrected=corrected)
        reviews = self._reviews()
        story = self._story(task["story_id"])
        report = {
            "review_id": f"REV-{len(reviews) + 1:03d}",
            "task_id": task_id,
            "reviewer": "independent-reviewer (simulated, isolated from development)",
            "result": verdict["result"],
            "critical_gaps": verdict["critical_gaps"],
            "major_gaps": verdict["major_gaps"],
            "minor_gaps": verdict["minor_gaps"],
            "findings": verdict["findings"],
            "verified_against": [
                "signed plan v" + str(self.run().plan_version),
                task["story_id"],
                *[ac["ac_id"] for ac in story["acceptance_criteria"]],
                "change summary", "test evidence",
            ],
            "created_at": now_iso(),
            "version": sum(1 for r in reviews if r["task_id"] == task_id) + 1,
            "provenance": "simulated",
        }
        reviews.append(report)
        self.store.write_json(reviews, "review", "reviews.json")
        # The ledger tracks one review artifact per task (stable id), so a
        # re-review is a new *version* of the same artifact — the display id
        # REV-00N stays unique per execution.
        self._record(
            artifact_id=f"REV-{task_id[-3:]}", artifact_type="review_report",
            payload=report, author=report["reviewer"],
            stage=Stage.BUILD_REVIEW, action="independent-review",
            outcome=report["result"],
            inputs=[task["story_id"], f"CHG-{task_id[-3:]}", f"TSTB-{task_id[-3:]}"],
            version=report["version"],
            previous_version=report["version"] - 1 if report["version"] > 1 else None,
        )

        gate = self.gate(GateId.INDEPENDENT_REVIEW)
        if report["result"] == "blocked":
            task["status"] = Status.BLOCKED.value
            task["current_activity"] = (
                f"Blocked by independent review — {report['major_gaps']} major "
                "gap(s); return to development"
            )
            gate.status = Status.BLOCKED
            outcome = "failed"
        else:
            task["status"] = Status.COMPLETED.value
            task["progress_pct"] = 100
            task["current_activity"] = "Independent review passed"
            self._unlock_dependents(tasks, task)
            outcome = "passed"
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)

        gate.conditions = gates.independent_review_gate(
            list(self._latest_reviews().values()), tasks
        )
        all_done = all(t["status"] == Status.COMPLETED.value for t in tasks)
        if all_done and gates.all_met(gate.conditions):
            gate.status = Status.PASSED
            gate.decided_by = report["reviewer"]
            gate.decided_at = now_iso()
            run = self.run()
            self._advance_stage(run, Stage.BUILD_REVIEW)
        self._save_gate(gate)
        self._activity(
            stage=Stage.BUILD_REVIEW, actor="independent-reviewer",
            actor_type="simulation", workflow="independent-review-gate",
            artifact=task_id, duration_s=20.0, outcome=outcome,
            details="; ".join(f["summary"] for f in report["findings"]) or
            "verified against acceptance criteria — no gaps",
        )
        return report

    def review_return_to_development(self, role: Role, task_id: str) -> None:
        roles.require("return_to_development", role)
        tasks = self._tasks()
        task = self._task(tasks, task_id)
        if task["status"] != Status.BLOCKED.value:
            raise EngineError(f"{task_id} is not blocked by review")
        task["status"] = Status.IN_PROGRESS.value
        task["progress_pct"] = 40
        task["current_activity"] = (
            "Returned to development with review findings attached"
        )
        task["last_activity"] = now_iso()
        self._save_tasks(tasks)
        self._activity(
            stage=Stage.BUILD_REVIEW, actor=role.value, actor_type="human",
            workflow="return-to-development", artifact=task_id,
            outcome="returned",
        )

    def _unlock_dependents(self, tasks: list[dict], completed: dict) -> None:
        done_stories = {
            t["story_id"] for t in tasks
            if t["status"] == Status.COMPLETED.value
        }
        for t in tasks:
            if t["status"] == Status.NOT_STARTED.value and all(
                dep in done_stories for dep in t.get("dependencies", [])
            ):
                t["status"] = Status.READY.value
                t["last_activity"] = now_iso()

    # --- quality (spec §10) -------------------------------------------------

    COVERAGE_THRESHOLD = 80

    def quality_run(self, role: Role) -> None:
        roles.require("run_quality_checks", role)
        if self.gate(GateId.INDEPENDENT_REVIEW).status != Status.PASSED:
            raise EngineError(
                "Quality aggregation opens after the independent-review gate "
                "(G2) passes for every task"
            )
        self._stage_in_progress(Stage.QUALITY)
        stories = self._stories()
        tasks = self._tasks()
        latest = self._latest_reviews()
        checks = self._compute_checks(stories, tasks, latest)
        passed = sum(1 for c in checks if c["status"] == "passed")
        applicable = sum(1 for c in checks if c["status"] != "not_applicable")
        report = {
            "checks": checks,
            "risks": [
                {
                    "risk_id": "RSK-001", "severity": "medium",
                    "description": (
                        "Status vocabulary and packet-completeness rules rest "
                        "on unresolved SME questions; implemented against "
                        "provisional definitions."
                    ),
                    "status": "open",
                },
            ],
            "exceptions": [
                {
                    "exception_id": "EXC-001",
                    "description": (
                        "US-007 (deployment/operations) carries no code "
                        "coverage; excluded from the coverage threshold as an "
                        "operational task."
                    ),
                    "approved_by": role.value,
                    "approved_at": now_iso(),
                },
            ],
            "quality_score": round(100 * passed / applicable) if applicable else 0,
            "score_note": (
                "Informational only. The gate is the explicit conditions "
                "below, never this number."
            ),
            "recommendation": "",
            "generated_at": now_iso(),
            "provenance": "simulated",
        }
        stale = self.store.read_json_or([], "staleness.json")
        conditions = gates.quality_gate(report, stale)
        report["recommendation"] = (
            "Ready for release" if gates.all_met(conditions)
            else "Not ready — unmet conditions listed on the gate"
        )
        self.store.write_json(report, "quality", "quality-report.json")
        self._record(
            artifact_id="QRPT-001", artifact_type="quality_report",
            payload=report, author="quality-aggregation (simulated)",
            stage=Stage.QUALITY, action="aggregate", outcome="created",
            inputs=sorted({f"REV-{t['task_id'][-3:]}" for t in tasks}
                          | {f"CHG-{t['task_id'][-3:]}" for t in tasks}),
        )
        self._activity(
            stage=Stage.QUALITY, actor="quality-aggregation",
            actor_type="simulation", workflow="quality-checks",
            duration_s=15.0, outcome="created",
            details=f"{passed}/{applicable} checks passed",
        )

    def _compute_checks(
        self, stories: list[dict], tasks: list[dict], latest: dict[str, dict]
    ) -> list[dict]:
        """Each row computed from run evidence, never asserted."""
        done = {t["story_id"]: t for t in tasks
                if t["status"] == Status.COMPLETED.value}
        all_acs = [(s, ac) for s in stories for ac in s["acceptance_criteria"]]
        tested_acs = {
            t["ac_id"] for task in tasks for t in task.get("tests", [])
        }
        tests = [t for task in tasks for t in task.get("tests", [])]
        green = [t for t in tests if t["current_result"] == "passed"]
        code_cov = [t["coverage_pct"] for t in tasks
                    if t["story_id"] != "US-007" and t.get("coverage_pct")]
        majors = sum(r["major_gaps"] for r in latest.values()
                     if r["result"] != "passed")

        def row(check_id, name, ok, evidence, owner="quality-aggregation",
                status=None):
            return {
                "check_id": check_id, "name": name,
                "status": status or ("passed" if ok else "failed"),
                "evidence": evidence, "owner": owner,
                "completed_at": now_iso(), "exception": "",
            }

        unmapped = [s["story_id"] for s in stories if not s.get("traces_to")]
        uncoded = [ac["ac_id"] for s, ac in all_acs if s["story_id"] not in done]
        untested = [ac["ac_id"] for _s, ac in all_acs if ac["ac_id"] not in tested_acs]
        return [
            row("QC-01", "Requirement-to-story mapping", not unmapped,
                f"{len(stories)} stories trace to REQ-2026-114"
                if not unmapped else f"unmapped: {', '.join(unmapped)}"),
            row("QC-02", "AC-to-code mapping", not uncoded,
                f"{len(all_acs)} criteria covered by completed tasks"
                if not uncoded else f"uncovered: {', '.join(uncoded)}"),
            row("QC-03", "AC-to-test mapping", not untested,
                f"{len(all_acs)} criteria each carry a test"
                if not untested else f"untested: {', '.join(untested)}"),
            row("QC-04", "Test execution", len(green) == len(tests) and tests,
                f"{len(green)}/{len(tests)} tests passing"),
            row("QC-05", "Code coverage",
                bool(code_cov) and min(code_cov) >= self.COVERAGE_THRESHOLD,
                f"minimum {min(code_cov)}% across implementation tasks "
                f"(threshold {self.COVERAGE_THRESHOLD}%)" if code_cov else "no data"),
            row("QC-06", "Security scan", True,
                "0 critical, 1 medium (tracked) — simulated scan"),
            row("QC-09", "Dependency scan", True,
                "no known-vulnerable dependencies — simulated scan"),
            row("QC-10", "Standards check", True,
                "27/27 engineering standards checks — simulated"),
            row("QC-07", "Independent-review gaps", majors == 0,
                "0 unresolved major gaps" if majors == 0
                else f"{majors} major gaps open"),
            row("QC-11", "Regression & integration", "US-006" in done,
                "US-006 regression and integration scenarios complete"
                if "US-006" in done else "US-006 not complete"),
            row("QC-12", "Performance check", True, "", status="not_applicable"),
            row("QC-08", "Operational readiness", "US-007" in done,
                "US-007 deployment, monitoring, runbook and handover prepared"
                if "US-007" in done else "US-007 not complete"),
        ]

    def quality_decide(self, role: Role) -> None:
        roles.require("decide_quality_gate", role)
        report = self.store.read_json_or(None, "quality", "quality-report.json")
        stale = self.store.read_json_or([], "staleness.json")
        conditions = gates.quality_gate(report, stale)
        gate = self.gate(GateId.QUALITY)
        gate.conditions = conditions
        if not gates.all_met(conditions):
            gate.status = Status.BLOCKED
            self._save_gate(gate)
            unmet = "; ".join(c["condition"] for c in conditions if not c["met"])
            self._activity(
                stage=Stage.QUALITY, actor=role.value, actor_type="human",
                workflow="quality-gate", outcome="failed", details=unmet,
            )
            raise EngineError(f"Quality gate blocked — unmet: {unmet}")
        gate.status = Status.PASSED
        gate.decided_by = role.value
        gate.decided_at = now_iso()
        self._save_gate(gate)
        run = self.run()
        self._advance_stage(run, Stage.QUALITY)
        self._activity(
            stage=Stage.QUALITY, actor=role.value, actor_type="human",
            workflow="quality-gate", outcome="passed",
        )

    # --- release (spec §11) -------------------------------------------------

    RELEASE_APPROVER_ROLES = (
        "business_owner", "engineering_lead", "qa_lead", "release_manager",
    )

    def _release(self) -> dict | None:
        return self.store.read_json_or(None, "release", "release-record.json")

    def release_request_approval(self, role: Role) -> None:
        roles.require("request_release_approval", role)
        if self.gate(GateId.QUALITY).status != Status.PASSED:
            raise EngineError("Release opens after the quality gate (G3) passes")
        self._stage_in_progress(Stage.RELEASE)
        if self._release() is not None:
            raise EngineError("Release approval has already been requested")
        record = {
            "release_id": "REL-2026R4-001",
            "epic_id": "EPIC-S7-001",
            "version": "1.0.0",
            "environment": "Production",
            "release_window": "2026-08-21 20:00–23:00 ET",
            "release_manager": "unassigned until approval",
            "feature_flag": "sponsor_claim_submission (off at deploy)",
            "rollback_plan": (
                "Disable the feature flag and restore the previous journey "
                "entry point; database changes are additive with a reverse "
                "migration. Validated in staging."
            ),
            "status": Status.WAITING_APPROVAL.value,
            "deployment": None,
            "handover": None,
            "created_at": now_iso(),
            "provenance": "simulated",
        }
        self.store.write_json(record, "release", "release-record.json")
        self.store.write_text(_DEPLOY_CHECKLIST, "release", "deployment-checklist.md")
        self.store.write_text(_ROLLBACK_PLAN, "release", "rollback-plan.md")
        self.store.write_text(_RUNBOOK, "release", "runbook.md")
        self._record(
            artifact_id=record["release_id"], artifact_type="release_record",
            payload=record, author=role.value, stage=Stage.RELEASE,
            action="request-approval", outcome="created",
            inputs=["QRPT-001", "PLAN-001"],
        )
        self._activity(
            stage=Stage.RELEASE, actor=role.value, actor_type="human",
            workflow="release-approval", outcome="requested",
        )

    def release_approve(
        self, role: Role, approver: str, note: str = "", decision: str = "approved"
    ) -> None:
        roles.require("approve_release", role)
        if self._release() is None:
            raise EngineError("Request release approval first")
        if decision not in ("approved", "rejected"):
            raise EngineError("Decision must be 'approved' or 'rejected'")
        if not approver.strip():
            raise EngineError("A named approver is required")
        approvals = self.store.read_ledger("approvals.jsonl")
        self.store.append(
            Approval(
                approval_id=f"APR-{len(approvals) + 1:03d}",
                subject="release",
                role=role,
                approver=approver.strip(),
                decision=decision,
                note=note,
            ),
            "approvals.jsonl",
        )
        gate = self.gate(GateId.RELEASE)
        if decision == "rejected":
            gate.status = Status.BLOCKED
            gate.note = note
            self._save_gate(gate)
            record = self._release()
            record["status"] = Status.BLOCKED.value
            self.store.write_json(record, "release", "release-record.json")
            self._activity(
                stage=Stage.RELEASE, actor=approver, actor_type="human",
                workflow="release-approval", outcome="rejected", details=note,
            )
            return
        self._activity(
            stage=Stage.RELEASE, actor=approver, actor_type="human",
            workflow="release-approval", outcome="approved",
            details=f"as {role.value}",
        )

    def release_deploy(self, role: Role) -> None:
        roles.require("deploy", role)
        record = self._release()
        if record is None:
            raise EngineError("Request release approval first")
        stale = self.store.read_json_or([], "staleness.json")
        approvals = self.store.read_ledger("approvals.jsonl")
        conditions = gates.release_gate(
            [g.model_dump(mode="json") for g in self.gates()],
            approvals, stale, self.RELEASE_APPROVER_ROLES,
        )
        gate = self.gate(GateId.RELEASE)
        gate.conditions = conditions
        if not gates.all_met(conditions):
            gate.status = Status.BLOCKED
            self._save_gate(gate)
            unmet = "; ".join(c["condition"] for c in conditions if not c["met"])
            self._activity(
                stage=Stage.RELEASE, actor=role.value, actor_type="human",
                workflow="release-gate", outcome="failed", details=unmet,
            )
            raise EngineError(f"Release gate blocked — unmet: {unmet}")
        gate.status = Status.PASSED
        gate.decided_by = role.value
        gate.decided_at = now_iso()
        self._save_gate(gate)

        record["status"] = Status.IN_PROGRESS.value
        record["release_manager"] = role.value
        deployment = {
            "deployment_id": "DEP-001",
            "environment": "Production",
            "pipeline_ref": "pipeline #126 (simulated)",
            "artifact_count": 14,
            "strategy": "blue-green behind sponsor_claim_submission flag",
            "status": Status.COMPLETED.value,
            "smoke_test_status": "passed (8/8 checks)",
            "post_checks": [
                "health endpoints green in both colours",
                "error rate within baseline",
                "no elevated latency on lookup service",
            ],
            "deployed_at": now_iso(),
        }
        record["deployment"] = deployment
        record["status"] = Status.COMPLETED.value
        self.store.write_json(record, "release", "release-record.json")
        self._record(
            artifact_id=deployment["deployment_id"], artifact_type="deployment",
            payload=deployment, author="deployment-pipeline (simulated)",
            stage=Stage.RELEASE, action="deploy", outcome="completed",
            inputs=[record["release_id"]],
        )
        for step, secs in [
            ("pre-deployment checks", 4.0), ("deploy to production", 9.0),
            ("smoke tests", 5.0), ("post-deployment checks", 4.0),
        ]:
            self._activity(
                stage=Stage.RELEASE, actor="deployment-pipeline",
                actor_type="simulation", workflow="deployment",
                artifact="DEP-001", duration_s=secs, outcome="passed",
                details=step,
            )

    def release_handover(self, role: Role) -> None:
        roles.require("complete_handover", role)
        record = self._release()
        if not record or not record.get("deployment"):
            raise EngineError("Deployment must complete before support handover")
        handover = {
            "support_team": "MapleSure Application Support (S1–S6 scope)",
            "runbook_ref": "release/runbook.md",
            "knowledge_article_ref": "KB-2026-0473 (demonstration)",
            "monitoring_alerts": [
                "submission-error-rate above baseline",
                "intake-handoff retry queue depth",
                "lookup-service latency p95",
            ],
            "escalation_path": "Support → Platform Team → Services Team on-call",
            "known_limitations": [
                "Status vocabulary provisional pending SME confirmation",
                "Partial-submission retention period unconfirmed",
            ],
            "hypercare_days": 7,
            "accepted_by": role.value,
            "accepted_at": now_iso(),
        }
        record["handover"] = handover
        self.store.write_json(record, "release", "release-record.json")
        self.store.write_text(_HANDOVER_DOC, "release", "support-handover.md")
        self._record(
            artifact_id="HND-001", artifact_type="support_handover",
            payload=handover, author=role.value, stage=Stage.RELEASE,
            action="handover", outcome="accepted", inputs=["DEP-001"],
        )
        run = self.run()
        self._advance_stage(run, Stage.RELEASE)
        run = self.run()
        run.status = Status.COMPLETED
        self._save_run(run)
        self._activity(
            stage=Stage.RELEASE, actor=role.value, actor_type="human",
            workflow="support-handover-approval", outcome="accepted",
            details="hypercare 7 days; run complete",
        )

    # --- staleness & self-correction (spec §15, §16) ------------------------

    def trigger_upstream_change(self, role: Role) -> None:
        """The demonstration's upstream change: an SME ruling amends the
        design after downstream work exists. Nothing downstream is touched —
        the ledger marks it stale, and the release gate blocks on it."""
        roles.require("trigger_upstream_change", role)
        design = self.store.read_json_or(None, "planning", "design.json")
        if design is None:
            raise EngineError("No design artifact yet; generate the plan first")
        if design["version"] > 1:
            raise EngineError("The upstream change has already been applied")
        design["version"] = 2
        design["rules"]["draft_retention"] = (
            "SME CONFIRMED: an in-progress submission is retained for 14 days "
            "before expiry, and the sponsor is notified at day 10."
        )
        self.store.write_json(design, "planning", "design.json")
        self._record(
            artifact_id="DES-001", artifact_type="design", payload=design,
            author=f"{role.value} (SME ruling)", stage=Stage.PLANNING,
            action="sme-ruling", outcome="amended", version=2,
            previous_version=1, inputs=["EPIC-S7-001", "ANL-001"],
        )
        stale = self.store.read_json_or([], "staleness.json")
        amendments = self.store.read_ledger("amendments.jsonl")
        self.store.append(
            {
                "amendment_id": f"AMD-{len(amendments) + 1:03d}",
                "reason": (
                    "SME ruling: draft retention is 14 days with a day-10 "
                    "notification — the provisional 30-day assumption in "
                    "DES-001 v1 is wrong."
                ),
                "initiator": role.value,
                "affected_artifacts": [s["artifact_id"] for s in stale],
                "impact_assessment": (
                    f"{len(stale)} downstream artifacts derive from DES-001 "
                    "and must be re-validated; release is blocked until they "
                    "are corrected."
                ),
                "required_changes": [
                    "Amend affected stories against DES-001 v2",
                    "Update implementation and test evidence",
                    "Re-run independent review",
                    "Re-evaluate quality and release gates",
                ],
                "implementation_status": "not_started",
                "verification_status": "not_started",
                "review_status": "not_started",
                "approval": None,
                "created_at": now_iso(),
            },
            "amendments.jsonl",
        )
        self._activity(
            stage=Stage.PLANNING, actor=role.value, actor_type="human",
            workflow="upstream-change", artifact="DES-001",
            outcome="amended",
            details=f"SME ruling on draft retention; {len(stale)} artifacts stale",
        )

    def run_self_correction(self, role: Role) -> None:
        """Controlled amendment execution: every stale artifact gets a **new
        version** re-validated against the changed upstream — never a silent
        update. Corrections land in original creation order so the ledger
        clears the staleness chain naturally."""
        roles.require("run_self_correction", role)
        stale = self.store.read_json_or([], "staleness.json")
        if not stale:
            raise EngineError("Nothing is stale; no correction to run")
        ledger = self.store.read_ledger("provenance.jsonl")
        order = {rec["artifact_id"]: i for i, rec in enumerate(ledger)}
        latest: dict[str, dict] = {}
        for rec in ledger:
            latest[rec["artifact_id"]] = rec

        self._activity(
            stage=Stage.QUALITY, actor=role.value, actor_type="human",
            workflow="self-correction", outcome="started",
            details=f"impact assessment: {len(stale)} artifacts to re-validate",
        )
        for item in sorted(stale, key=lambda s: order.get(s["artifact_id"], 0)):
            rec = latest[item["artifact_id"]]
            payload = {
                "artifact_id": rec["artifact_id"],
                "revalidated_against": "DES-001 v2 (14-day draft retention)",
                "previous_sha256": rec["sha256"],
            }
            if rec["artifact_type"] == "story":
                stories = self._stories()
                target = next(
                    (s for s in stories if s["story_id"] == rec["artifact_id"]), None
                )
                if target is not None:
                    target["version"] += 1
                    self.store.write_json(stories, "planning", "stories.json")
            if rec["artifact_type"] == "review_report":
                # Stable ledger id REV-<suffix> maps to the task's reviews.
                suffix = rec["artifact_id"].split("-")[-1]
                reviews = self._reviews()
                base = [r for r in reviews
                        if r["task_id"].endswith(suffix)][-1]
                reviews.append({
                    **base,
                    "review_id": f"REV-{len(reviews) + 1:03d}",
                    "result": "passed",
                    "version": base["version"] + 1,
                    "created_at": now_iso(),
                })
                self.store.write_json(reviews, "review", "reviews.json")
            self._record(
                artifact_id=rec["artifact_id"],
                artifact_type=rec["artifact_type"],
                payload=payload,
                author="self-correction (simulated)",
                stage=Stage.QUALITY,
                action="re-validate",
                outcome="amended",
                inputs=rec.get("inputs", []),
                version=rec["version"] + 1,
                previous_version=rec["version"],
            )
            self._activity(
                stage=Stage.QUALITY, actor="self-correction",
                actor_type="simulation", workflow="self-correction",
                artifact=rec["artifact_id"], duration_s=8.0,
                outcome="amended",
                details=f"re-validated against DES-001 v2 as v{rec['version'] + 1}",
            )

        remaining = self.store.read_json_or([], "staleness.json")
        amendments = self.store.read_ledger("amendments.jsonl")
        if amendments:
            done = dict(amendments[-1])
            done.update(
                implementation_status="completed",
                verification_status="completed" if not remaining else "failed",
                review_status="completed",
                completed_at=now_iso(),
            )
            self.store.append(done, "amendments.jsonl")
        self._activity(
            stage=Stage.QUALITY, actor="self-correction",
            actor_type="simulation", workflow="self-correction",
            outcome="completed" if not remaining else "failed",
            details="all stale artifacts re-validated" if not remaining
            else f"{len(remaining)} artifacts still stale",
        )

    # --- traceability (spec §12) --------------------------------------------

    def traceability(self) -> list[dict]:
        """One row per acceptance criterion: the full chain from requirement
        to handover, from model fields — never descriptive text."""
        stories = self._stories()
        tasks = {t["story_id"]: t for t in self._tasks()}
        latest_reviews = self._latest_reviews()
        quality = self.store.read_json_or(None, "quality", "quality-report.json")
        release = self._release()
        rows: list[dict] = []
        for s in stories:
            task = tasks.get(s["story_id"])
            review = latest_reviews.get(task["task_id"]) if task else None
            for ac in s["acceptance_criteria"]:
                tests = [
                    t["test_id"] for t in (task or {}).get("tests", [])
                    if t["ac_id"] == ac["ac_id"]
                ]
                rows.append({
                    "requirement": seed.REQUIREMENT.request_id,
                    "design": "DES-001",
                    "epic": s["epic_id"],
                    "story": s["story_id"],
                    "ac": ac["ac_id"],
                    "task": task["task_id"] if task else None,
                    "change": f"CHG-{task['task_id'][-3:]}"
                    if task and task.get("files_changed") else None,
                    "pr": task.get("pr_ref") if task else None,
                    "tests": tests,
                    "review": review["review_id"] if review else None,
                    "review_result": review["result"] if review else None,
                    "quality": "QRPT-001" if quality else None,
                    "deployment": release["deployment"]["deployment_id"]
                    if release and release.get("deployment") else None,
                    "handover": "HND-001"
                    if release and release.get("handover") else None,
                })
        return rows

    # --- workspace handoff (CLAUDE.md § Design review, item 1) -------------

    def assignees(self) -> list[str]:
        """Everyone currently named as an owner on a story or task."""
        from s7_delivery.factory import workspace as _workspace

        return _workspace.assignees(self._stories(), self._tasks())

    def generate_workspace(self, role: Role, assignee: str) -> dict:
        """Package one person's stories and tasks into a handoff bundle.

        Writes `workspaces/<slug>/workspace.json` and `workspace.md` — a
        stable path any surface (or a fresh clone with no browser at all)
        can read deterministically, per the artifact-plane discipline
        `s7_delivery/models.py` already documents for the upstream stages.
        """
        roles.require("generate_workspace", role)
        assignee = assignee.strip()
        if not assignee:
            raise EngineError("Assignee name is required")

        from s7_delivery.factory import workspace as _workspace

        slug = _workspace.slugify(assignee)
        existing = self.store.read_json_or(None, "workspaces", slug, "workspace.json")
        version = (existing or {}).get("version", 0) + 1

        design = self.store.read_json_or(None, "planning", "design.json")
        pkg = _workspace.build_package(
            self.run_id, assignee, self._stories(), self._tasks(), design,
            version=version,
        )
        payload = pkg.model_dump(mode="json")
        self.store.write_json(payload, "workspaces", slug, "workspace.json")
        self.store.write_text(
            _workspace.render_markdown(pkg), "workspaces", slug, "workspace.md"
        )
        stage = Stage.BUILD_REVIEW if self.run().plan_locked else Stage.PLANNING
        self._record(
            artifact_id=pkg.workspace_id, artifact_type="workspace", payload=payload,
            author=role.value, stage=stage, action="generate",
            outcome=f"{len(pkg.stories)} stories, {len(pkg.tasks)} tasks"
            + (f", {len(pkg.blocked)} blocked" if pkg.blocked else ""),
            inputs=[s.story_id for s in pkg.stories] + [t.task_id for t in pkg.tasks],
            version=version,
            previous_version=version - 1 if version > 1 else None,
        )
        self._activity(
            stage=stage, actor=role.value, actor_type="human",
            workflow="workspace-generate", artifact=pkg.workspace_id,
            outcome="created", details=f"for {assignee}",
        )
        return payload

    def read_workspace(self, assignee: str) -> dict:
        from s7_delivery.factory import workspace as _workspace

        return self.store.read_json("workspaces", _workspace.slugify(assignee), "workspace.json")

    def read_workspace_markdown(self, assignee: str) -> str:
        from s7_delivery.factory import workspace as _workspace

        return self.store.read_text("workspaces", _workspace.slugify(assignee), "workspace.md")

    def _seed_tasks(self, stories: list[dict]) -> None:
        """Create the work queue from the signed plan — one task per
        implementation story, dependency order preserved. The demo processes
        one task at a time (spec §9A); US-003 carries the deliberate defect."""
        from s7_delivery.factory.models import TaskRecord

        tasks = []
        for i, s in enumerate(stories, start=1):
            tasks.append(
                TaskRecord(
                    task_id=f"TASK-{i:03d}",
                    story_id=s["story_id"],
                    summary=s["title"],
                    accountable_team=s["accountable_team"],
                    dependencies=s.get("dependencies", []),
                    status=Status.READY if not s.get("dependencies") else Status.NOT_STARTED,
                ).model_dump(mode="json")
            )
        self.store.write_json(tasks, "build", "tasks.json")

    @staticmethod
    def _plan_markdown(plan: dict, stories: list[dict]) -> str:
        lines = [
            "# Delivery plan — EPIC-S7-001",
            "",
            f"Version {plan['plan_version']}, signed by {plan['signed_by']} "
            f"at {plan['signed_at']}.",
            "",
            "This signed plan is the contract for downstream work. Changes "
            "after sign-off require an amendment with its own approval.",
            "",
            "| Story | Title | Team | Component | Depends on | Est | Sprint |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in stories:
            lines.append(
                f"| {s['story_id']} | {s['title']} | {s['accountable_team']} "
                f"| {s['target_component']} | {', '.join(s.get('dependencies', [])) or '—'} "
                f"| {s['estimate']} | {s['sprint']} |"
            )
        lines += ["", "## Acceptance criteria", ""]
        for s in stories:
            lines.append(f"### {s['story_id']} — {s['title']}")
            for ac in s["acceptance_criteria"]:
                lines.append(f"- **{ac['ac_id']}** {ac['text']}")
            lines.append("")
        return "\n".join(lines)
