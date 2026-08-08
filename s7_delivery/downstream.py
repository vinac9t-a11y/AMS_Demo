"""Build → test → review for one AGENTIC task. Happy path, hard-capped.

Three role-labelled model calls — Developer, Tester, Reviewer — over plain
orchestration. This is deliberately *not* an agent framework (the 2026-08-04
review rejected going agentic on this timeline); the roles are visible names
for sequential stages, which is all the demo claims they are.

Every artifact lands under the given root:

    root/app/           the generated application + its generated tests
    root/events.jsonl   one JSON line per agent action — the console's feed
    root/review.json    the Reviewer's verdict against the acceptance criteria

The pytest run over the generated files is real: red tests flip the result to
not-ok and are reported, never hidden (§ Determinism — "None is an admission",
applied to a whole lane).

Events line schema (the contract the console animates):
    {"ts": float, "agent": "developer"|"tester"|"reviewer"|"system",
     "action": str, "artifact": str|null, "status": "start"|"done"|"fail"}
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from common.llm import complete
from s7_delivery.generate import parse_json_block
from s7_delivery.models import Task, UserStory

_SYSTEM = (
    "You are an agent in MapleSure Insurance's automated delivery lane. "
    "MapleSure is a fictional insurer in a tabletop exercise. Output strict "
    "JSON matching the schema given in the task — no prose, no markdown "
    "fences. Generated code uses plain HTML/CSS/JS and Python stdlib only: "
    "no CDNs, no frameworks, no network calls, nothing fetched at runtime."
)


# pytest timing varies run to run; anything embedded in a prompt must be
# deterministic or the prompt hash changes and replay misses the recording.
_TIMING = re.compile(r"\d+\.\d+s")

MAX_REVISION_ROUNDS = 2
"""Hard cap on review→fix rounds. At the cap, remaining failures are
reported in the events and the result — never presented as success."""


def _sanitize(test_output: str) -> str:
    return _TIMING.sub("N.NNs", test_output)


@dataclass
class LaneResult:
    ok: bool
    app_dir: Path
    events_path: Path
    test_output: str
    review: dict
    revised: bool = False
    """True when the reviewer rejected the first build and the Developer's
    bounded revision pass produced the final artifact."""


class _Events:
    def __init__(self, path: Path):
        self.path = path
        path.write_text("")

    def emit(
        self, agent: str, action: str, artifact: str | None = None, status: str = "done"
    ) -> None:
        line = {"ts": time.time(), "agent": agent, "action": action,
                "artifact": artifact, "status": status}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")


def _write_files(data: dict, dest: Path) -> list[str]:
    """Write the files an agent returned. Paths are flattened to basenames:
    the generated app is deliberately flat, and a model reply must not be able
    to write outside its directory."""
    names: list[str] = []
    for f in data["files"]:
        rel = Path(str(f["path"])).name
        (dest / rel).write_text(str(f["content"]), encoding="utf-8")
        names.append(rel)
    return names


def _criteria_block(story: UserStory, task: Task) -> str:
    wanted = set(task.satisfies) or {a.id for a in story.acceptance}
    return "\n".join(f"- {a.id}: {a.text}" for a in story.acceptance if a.id in wanted)


def _developer_prompt(story: UserStory, task: Task) -> str:
    return f"""You are the Developer agent. Your task:

Task {task.id} ({task.stream.value}): {task.summary}
Story {story.id}: {story.title}
Narrative: {story.narrative}
Acceptance criteria this task must satisfy:
{_criteria_block(story, task)}

Build a single-page MapleSure SponsorConnect screen: the plan sponsor
disability claim submission journey. One self-contained index.html
(inline CSS and JS, professional insurer-portal look, works when opened as a
local file). Required behaviour, happy path only:

- Fields: policy number (id="policy-number") and member id (id="member-id"),
  with a "Look up member" button that fills a member-details panel from a
  small mock data object defined in the page's own JS (no fetch, no backend).
- A claim details section: last day worked (date), first day absent (date),
  nature of absence (select), and a free-text details field.
- A document upload input (id="documents") with the `multiple` attribute and
  a visible list of chosen file names.
- The whole thing wrapped in a form (id="claim-form"). Submitting hides the
  form and shows a confirmation panel (id="confirmation") containing a
  reference number like MS-2026-08-XXXX generated in JS and the status text
  "Received".
- A small footer note: "MapleSure Insurance — fictional demo application".

JSON schema: {{"files": [{{"path": "index.html", "content": str}}]}}"""


def _tester_prompt(story: UserStory, task: Task, files: list[str], app_dir: Path) -> str:
    generated = "\n\n".join(
        f"--- {name} ---\n{(app_dir / name).read_text(encoding='utf-8')}" for name in files
    )
    return f"""You are the Tester agent. The Developer produced these files for
task {task.id} ({task.summary}):

{generated}

Acceptance criteria:
{_criteria_block(story, task)}

Write pytest tests (a single test_app.py) that verify the happy path
STRUCTURALLY against the actual file above — read index.html from
Path(__file__).parent and assert what the criteria need: the form and its
required field ids exist, the upload input allows multiple files, the
confirmation panel and status markup exist, the member lookup mock data is
present. 4 to 6 focused tests, stdlib + pytest only, no browser, no server,
no network. Every assertion must hold for the file exactly as shown above,
and must be independent of the current date, time, or environment — never
hard-code a year, month, or timestamp; where the page generates a value at
runtime, assert the generating code exists, not the value it would produce
today.

JSON schema: {{"files": [{{"path": "test_app.py", "content": str}}]}}"""


def _reviewer_prompt(story: UserStory, task: Task, app_dir: Path, test_output: str) -> str:
    listing = "\n".join(sorted(p.name for p in app_dir.iterdir()))
    html = (app_dir / "index.html").read_text(encoding="utf-8") if (app_dir / "index.html").exists() else ""
    return f"""You are the Reviewer agent — a second, independent check before
anything reaches a human. You did not write this code. Verify the Developer's
output for task {task.id} against the acceptance criteria, using the evidence
below. Be strict: an unmet criterion is a fail even if the code looks nice.

Acceptance criteria:
{_criteria_block(story, task)}

Files produced:
{listing}

index.html content:
{html}

pytest output:
{test_output}

JSON schema: {{"verdict": "pass" | "fail",
"criteria": [{{"id": str, "met": bool, "note": str}}],
"notes": [str]}}"""


def _revision_prompt(
    story: UserStory, task: Task, app_dir: Path, review: dict, test_output: str
) -> str:
    html = (app_dir / "index.html").read_text(encoding="utf-8")
    tests = (app_dir / "test_app.py").read_text(encoding="utf-8") if (app_dir / "test_app.py").exists() else ""
    findings = "\n".join(
        f"- {c.get('id')}: {'met' if c.get('met') else 'NOT MET'} — {c.get('note', '')}"
        for c in review.get("criteria", [])
    )
    return f"""You are the Developer agent. An independent Reviewer rejected
your build for task {task.id}. Fix every NOT MET finding. Do not argue with
the findings; address them.

Reviewer findings:
{findings}

Reviewer notes: {review.get('notes')}

Acceptance criteria:
{_criteria_block(story, task)}

Your current index.html:
{html}

The Tester's tests, which must still pass unchanged:
{tests}

Last pytest output: {test_output}

Return the complete revised index.html (full file, not a diff). Keep every
element id and structural marker the tests rely on. Same constraints as
before: single self-contained file, inline CSS/JS, mock data in-page, no
fetch, no network, happy path only.

JSON schema: {{"files": [{{"path": "index.html", "content": str}}]}}"""


def _test_revision_prompt(
    story: UserStory, task: Task, app_dir: Path, review: dict, test_output: str
) -> str:
    html = (app_dir / "index.html").read_text(encoding="utf-8")
    tests = (app_dir / "test_app.py").read_text(encoding="utf-8")
    findings = "\n".join(
        f"- {c.get('id')}: {'met' if c.get('met') else 'NOT MET'} — {c.get('note', '')}"
        for c in review.get("criteria", [])
    )
    return f"""You are the Tester agent. Your tests are red against the current
build and the independent Reviewer's diagnosis is that at least one test is
itself defective. Fix the tests — and only what is defective in them. A fixed
test must still genuinely verify its acceptance criterion against the file as
it exists; do not weaken or delete a valid assertion to force green.

Reviewer findings:
{findings}

Current index.html:
{html}

Current test_app.py:
{tests}

pytest output:
{test_output}

Assertions must be independent of the current date, time, or environment —
assert that generating code exists rather than the value it would produce
today. Return the complete revised test_app.py.

JSON schema: {{"files": [{{"path": "test_app.py", "content": str}}]}}"""


def _run_pytest(app_dir: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", str(app_dir)],
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode == 0, proc.stdout


def run_lane(story: UserStory, task: Task, root: Path) -> LaneResult:
    app_dir = root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    ev = _Events(root / "events.jsonl")

    ev.emit("developer", f"picked up {task.id}: {task.summary}", status="start")
    dev = parse_json_block(
        complete(_developer_prompt(story, task), system=_SYSTEM, json_mode=True,
                 cache_key="s7:downstream:developer")
    )
    files = _write_files(dev, app_dir)
    ev.emit("developer", "wrote application code", artifact=", ".join(files))

    ev.emit("tester", "writing tests against acceptance criteria", status="start")
    tst = parse_json_block(
        complete(_tester_prompt(story, task, files, app_dir), system=_SYSTEM, json_mode=True,
                 cache_key="s7:downstream:tester")
    )
    test_files = _write_files(tst, app_dir)
    ev.emit("tester", "wrote tests", artifact=", ".join(test_files))

    ev.emit("tester", "running pytest", status="start")
    green, test_out = _run_pytest(app_dir)
    ev.emit(
        "tester",
        "tests green" if green else "tests FAILED",
        artifact=test_files[0] if test_files else None,
        status="done" if green else "fail",
    )

    ev.emit("reviewer", "independent review against acceptance criteria", status="start")
    review = parse_json_block(
        complete(_reviewer_prompt(story, task, app_dir, _sanitize(test_out)), system=_SYSTEM,
                 json_mode=True, cache_key="s7:downstream:reviewer")
    )
    verdict_ok = review.get("verdict") == "pass"
    ev.emit(
        "reviewer",
        f"verdict: {review.get('verdict')}",
        artifact="review.json",
        status="done" if verdict_ok else "fail",
    )

    # Bounded revision loop, per the reference architecture's hard-capped TDD
    # loop: the reviewer's findings triage back to the role that must fix
    # them, at most MAX_REVISION_ROUNDS times. If the result still fails at
    # the cap, that is reported, not hidden.
    revised = False
    rounds = 0
    while not (green and verdict_ok) and rounds < MAX_REVISION_ROUNDS:
        rounds += 1
        revised = True
        if rounds == 1:
            (root / "review_first.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
        ev.emit("developer", f"revision {rounds}: addressing reviewer findings", status="start")
        fix = parse_json_block(
            complete(_revision_prompt(story, task, app_dir, review, _sanitize(test_out)),
                     system=_SYSTEM, json_mode=True,
                     cache_key=f"s7:downstream:developer:fix{rounds}")
        )
        files = _write_files(fix, app_dir)
        ev.emit("developer", "applied fixes from review", artifact=", ".join(files))

        ev.emit("tester", "re-running pytest against revised build", status="start")
        green, test_out = _run_pytest(app_dir)
        ev.emit("tester", "tests green" if green else "tests FAILED",
                status="done" if green else "fail")

        # Triage to the role that must fix it: if the tests are still red
        # after the Developer's pass, the defect may be in the tests — the
        # Tester gets one bounded fix of its own, then evidence decides.
        if not green:
            ev.emit("tester", "revision: fixing defective test per review diagnosis",
                    status="start")
            fixt = parse_json_block(
                complete(_test_revision_prompt(story, task, app_dir, review, _sanitize(test_out)),
                         system=_SYSTEM, json_mode=True,
                         cache_key=f"s7:downstream:tester:fix{rounds}")
            )
            _write_files(fixt, app_dir)
            green, test_out = _run_pytest(app_dir)
            ev.emit("tester", "tests green" if green else "tests still FAILED",
                    status="done" if green else "fail")

        ev.emit("reviewer", "re-review of revised build", status="start")
        review = parse_json_block(
            complete(_reviewer_prompt(story, task, app_dir, _sanitize(test_out)),
                     system=_SYSTEM, json_mode=True,
                     cache_key=f"s7:downstream:reviewer:recheck{rounds}")
        )
        verdict_ok = review.get("verdict") == "pass"
        ev.emit("reviewer", f"verdict: {review.get('verdict')}", artifact="review.json",
                status="done" if verdict_ok else "fail")

    (root / "review.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    ok = green and verdict_ok
    ev.emit(
        "system",
        "lane complete — ready for release gate" if ok else "lane finished with failures",
        status="done" if ok else "fail",
    )
    return LaneResult(
        ok=ok,
        app_dir=app_dir,
        events_path=ev.path,
        test_output=test_out[-2000:],
        review=review,
        revised=revised,
    )
