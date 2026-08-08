"""Per-assignee workspace bundles — the app/CLI handoff artifact.

CLAUDE.md § Design review — 2026-08-04, item 1 records the resolution to the
strongest challenge raised against a standalone UI: an AI-SDLC is developer
centric, and context does not survive a surface switch if the handoff is
conversational. It survives fine if the handoff is *a file at a deterministic
path, validated against a schema* — the artifact plane already used for every
other stage output.

This module is that handoff for a single named person: it filters the run's
stories and tasks down to the ones they own, folds in the design context a
developer needs to be grounded (item 2 of the same review — "each target
repository carries an `architecture.md`... any call from any surface reads
it"), and flags anything blocked on a dependency that has not cleared yet.

Nothing here is AI output. It is mechanical packaging of artifacts the engine
already produced and already labelled, so the bundle's own provenance is
`SIMULATED` — the same label every other engine-assembled record carries.
"""

from __future__ import annotations

import re

from s7_delivery.factory.models import (
    Status,
    WorkspacePackage,
    WorkspaceStoryRef,
    WorkspaceTaskRef,
)

_UNSAFE = re.compile(r"[^A-Za-z0-9-]+")

_DONE_STATUSES = {Status.PASSED, Status.COMPLETED}


def slugify(name: str) -> str:
    """A path-safe segment for an assignee name.

    Deliberately narrower than the store's own `_SAFE_SEGMENT` rule (which
    also allows `.`): dots are collapsed into the same separator as spaces
    and punctuation, so a run of them can never survive into a `..` sequence
    or a trailing dot. A display name like "A. Ng" or "Priya N." becomes a
    plain `a-ng` / `priya-n` — safe as a run-store path segment without
    relying solely on the store's own defence-in-depth check. Never
    round-tripped back to a display name — the display name is carried
    separately in `WorkspacePackage.assignee`.
    """
    slug = _UNSAFE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        slug = "unassigned"
    if not slug[0].isalnum():
        slug = f"a-{slug}"
    return slug


def assignees(stories: list[dict], tasks: list[dict]) -> list[str]:
    """Distinct, non-empty owner names across stories and tasks, sorted."""
    names = {s.get("owner", "").strip() for s in stories}
    names |= {t.get("owner", "").strip() for t in tasks}
    names.discard("")
    return sorted(names)


def _story_ref(s: dict) -> WorkspaceStoryRef:
    return WorkspaceStoryRef(
        story_id=s["story_id"],
        title=s["title"],
        purpose=s.get("purpose", ""),
        status=s.get("status", Status.READY),
        target_application=s.get("target_application", ""),
        target_component=s.get("target_component", ""),
        target_repository=s.get("target_repository", ""),
        acceptance_criteria=s.get("acceptance_criteria", []),
        dependencies=s.get("dependencies", []),
        estimate=s.get("estimate", 0),
        sprint=s.get("sprint", 1),
        risk=s.get("risk", "low"),
        version=s.get("version", 1),
    )


def _task_ref(t: dict) -> WorkspaceTaskRef:
    return WorkspaceTaskRef(
        task_id=t["task_id"],
        story_id=t["story_id"],
        summary=t.get("summary", ""),
        status=t.get("status", Status.NOT_STARTED),
        dependencies=t.get("dependencies", []),
        progress_pct=t.get("progress_pct", 0),
        tests=t.get("tests", []),
        version=t.get("version", 1),
    )


def build_package(
    run_id: str,
    assignee: str,
    stories: list[dict],
    tasks: list[dict],
    design: dict | None,
    *,
    version: int = 1,
) -> WorkspacePackage:
    """Assemble the bundle for one assignee.

    A story is included if its `owner` matches; a task is included if its own
    `owner` matches, OR its parent story is owned by this assignee and the
    task itself has not been explicitly reassigned to someone else — the
    common case where a lead assigns a story and the same person's name
    should not have to be re-typed onto every task under it.
    """
    owned_story_ids = {s["story_id"] for s in stories if s.get("owner") == assignee}

    def task_belongs(t: dict) -> bool:
        if t.get("owner"):
            return t["owner"] == assignee
        return t.get("story_id") in owned_story_ids

    my_stories = [s for s in stories if s["story_id"] in owned_story_ids]
    my_tasks = [t for t in tasks if task_belongs(t)]

    blocked: list[str] = []
    status_by_story = {s["story_id"]: s.get("status") for s in stories}
    status_by_task = {t["task_id"]: t.get("status") for t in tasks}

    for s in my_stories:
        for dep in s.get("dependencies", []):
            dep_status = status_by_story.get(dep)
            if dep_status not in (Status.PASSED.value, Status.COMPLETED.value):
                blocked.append(f"{s['story_id']} waits on {dep} ({dep_status or 'unknown'})")

    for t in my_tasks:
        for dep in t.get("dependencies", []):
            dep_status = status_by_task.get(dep)
            if dep_status not in (Status.PASSED.value, Status.COMPLETED.value):
                blocked.append(f"{t['task_id']} waits on {dep} ({dep_status or 'unknown'})")

    design_rules = dict((design or {}).get("rules", {}))

    story_refs = [_story_ref(s) for s in sorted(my_stories, key=lambda s: s["story_id"])]
    task_refs = [_task_ref(t) for t in sorted(my_tasks, key=lambda t: t["task_id"])]

    return WorkspacePackage(
        workspace_id=f"WS-{run_id}-{slugify(assignee).upper()}",
        run_id=run_id,
        assignee=assignee,
        stories=story_refs,
        tasks=task_refs,
        design_rules=design_rules,
        blocked=blocked,
        version=version,
    )


def render_markdown(pkg: WorkspacePackage) -> str:
    """The handoff document — grounding plus the assigned work, one file."""
    lines = [
        f"# Workspace — {pkg.assignee}",
        "",
        f"Run `{pkg.run_id}` · generated `{pkg.generated_at}` · "
        f"`{pkg.provenance.value.upper()}` (mechanically assembled from "
        "already-labelled artifacts, not AI output).",
        "",
        "This file is the handoff at the app/CLI boundary (CLAUDE.md § Design "
        "review, item 1): everything below is what you need to start work "
        "without going back to the Control Centre.",
        "",
    ]

    if pkg.blocked:
        lines += ["## Blocked", ""]
        lines += [f"- ⚠️ {b}" for b in pkg.blocked]
        lines.append("")

    if pkg.design_rules:
        lines += ["## Design context", ""]
        for key, value in pkg.design_rules.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    lines += ["## Stories", ""]
    if not pkg.stories:
        lines.append("_No stories are currently assigned to this person._")
    for s in pkg.stories:
        lines.append(f"### {s.story_id} — {s.title} (`{s.status.value}`)")
        lines.append("")
        lines.append(s.purpose or "_No purpose recorded._")
        lines.append("")
        lines.append(
            f"Target: `{s.target_repository}` / `{s.target_component}` "
            f"({s.target_application}) · {s.estimate} pts · Sprint {s.sprint} · "
            f"risk {s.risk}"
        )
        if s.dependencies:
            lines.append(f"Depends on: {', '.join(s.dependencies)}")
        lines.append("")
        lines.append("Acceptance criteria:")
        for ac in s.acceptance_criteria:
            lines.append(f"- **{ac.ac_id}** {ac.text}")
        lines.append("")

    lines += ["## Tasks", ""]
    if not pkg.tasks:
        lines.append("_No tasks are currently assigned to this person._")
    for t in pkg.tasks:
        lines.append(
            f"- **{t.task_id}** ({t.story_id}) — {t.summary} — "
            f"`{t.status.value}`, {t.progress_pct}% "
            + (f", depends on {', '.join(t.dependencies)}" if t.dependencies else "")
        )
    lines.append("")

    return "\n".join(lines)
