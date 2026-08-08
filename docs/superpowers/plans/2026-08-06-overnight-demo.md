# Overnight Demo Build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** By 08:00 Eastern, the console demos a real recorded model run: five-gate overview → epic → assessment → design → sign-off gate → stories → one downstream developer lane (code + tests green) → release gate → a generated MapleSure form opens.

**Architecture:** A new `claude_cli` provider in `common/llm.py` shells out to `claude -p` at record time only; the demo runs in `LLM_MODE=replay` from committed recordings. A new `s7_delivery/generate.py` produces the same `models.py` shapes `staged.py` fakes, selected by `S7_ARTIFACTS=ai` with automatic fallback to staged. A new `s7_delivery/downstream.py` runs Developer → Tester → pytest → Reviewer for one AGENTIC task, writing artifacts + an events JSONL the console animates.

**Tech Stack:** Plain Python stdlib (subprocess, json, http.server), existing console (vanilla JS, no build step), pytest.

## Global Constraints

- Hard rule 2: no client/company names anywhere — the fiction is **MapleSure Insurance**. The call transcript and its names stay out of the repo.
- Hard rule 3: no keys in code. The `claude_cli` provider uses the CLI's own login.
- Hard rule 4: demo-time path must not require Claude Code, network, or any API key — `LLM_MODE=replay` from committed recordings only.
- Staged-labelling rule: any stage without a clean recording keeps `Provenance.STAGED` and its badge. No third option.
- Existing 60 tests stay green: `python -m pytest -q` before every commit.
- Time budgets are hard. If a task blows its budget by 50%, invoke its fallback from the spec (`docs/superpowers/specs/2026-08-06-overnight-demo-design.md` § Failure fallbacks) and move on.

---

### Task 1: `claude_cli` provider (budget: 45 min)

**Files:**
- Modify: `common/llm.py` (registry at `_PROVIDER_CALLERS` line ~563, `_PROVIDER_STREAMERS` line ~571, `_PROVIDER_NAMES` line 29, `_model_for` line ~124)
- Test: `tests/test_llm_claude_cli.py`

**Interfaces:**
- Produces: provider name `"claude_cli"` usable via `LLM_PROVIDER=claude_cli`; caller `_call_claude_cli(prompt, system, json_mode) -> tuple[str, Usage]`.
- Consumes: existing `Usage`, `LLMError`, `_int_or_none` in `common/llm.py`.

- [ ] **Step 1: Write the failing test** (monkeypatch subprocess — no real CLI call in tests)

```python
"""tests/test_llm_claude_cli.py"""
import json
import subprocess
import common.llm as llm


def _fake_run(payload):
    def fake(cmd, **kwargs):
        fake.cmd = cmd
        fake.stdin = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
    return fake


def test_claude_cli_parses_result_and_usage(monkeypatch):
    payload = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "hello from the model",
        "usage": {"input_tokens": 10, "output_tokens": 5,
                  "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2},
    }
    fake = _fake_run(payload)
    monkeypatch.setattr(subprocess, "run", fake)
    text, usage = llm._call_claude_cli("say hello", None, False)
    assert text == "hello from the model"
    assert usage.input_tokens == 10
    assert usage.cache_read_tokens == 3
    assert "claude" == fake.cmd[0] and "-p" in fake.cmd


def test_claude_cli_json_mode_appends_instruction(monkeypatch):
    payload = {"is_error": False, "result": "{}", "usage": {}}
    fake = _fake_run(payload)
    monkeypatch.setattr(subprocess, "run", fake)
    llm._call_claude_cli("give me json", "sys prompt", True)
    assert "JSON only" in fake.stdin
    assert "--append-system-prompt" in fake.cmd


def test_claude_cli_error_result_raises(monkeypatch):
    payload = {"is_error": True, "result": "boom"}
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    try:
        llm._call_claude_cli("x", None, False)
        assert False, "should have raised"
    except llm.LLMError as exc:
        assert "boom" in str(exc)


def test_claude_cli_registered():
    assert "claude_cli" in llm._PROVIDER_CALLERS
    assert "claude_cli" in llm._PROVIDER_STREAMERS
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_llm_claude_cli.py -q` → FAIL (`_call_claude_cli` not defined).

- [ ] **Step 3: Implement.** In `common/llm.py`, near the other `_call_*` functions (after `_call_ollama`, ~line 405):

```python
def _claude_cli_usage(raw: dict[str, Any]) -> Usage:
    u = raw.get("usage") or {}
    return Usage(
        input_tokens=_int_or_none(u.get("input_tokens")),
        output_tokens=_int_or_none(u.get("output_tokens")),
        cache_read_tokens=_int_or_none(u.get("cache_read_input_tokens")),
        cache_write_tokens=_int_or_none(u.get("cache_creation_input_tokens")),
    )


def _call_claude_cli(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    """Record-time provider: shells out to the local `claude` CLI (headless).

    Demo-time never reaches this — the demo runs in replay mode — so the
    dependency on Claude Code exists only on the machine that records.
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    model = os.environ.get("CLAUDE_CLI_MODEL")
    if model:
        cmd += ["--model", model]
    if system:
        cmd += ["--append-system-prompt", system]
    text = prompt
    if json_mode:
        text += "\n\nRespond with valid JSON only — no prose, no code fences."
    try:
        proc = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=900)
    except FileNotFoundError as exc:
        raise LLMError("claude CLI not found on PATH; LLM_PROVIDER=claude_cli is record-time only") from exc
    if proc.returncode != 0:
        raise LLMError(f"claude CLI exited {proc.returncode}: {proc.stderr[-500:]}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise LLMError(f"claude CLI error result: {str(payload.get('result'))[:300]}")
    return str(payload.get("result", "")), _claude_cli_usage(payload)
```

Then register it. Check exact `Usage` field names against `_anthropic_usage` (line 67) and adjust if they differ. Add `import subprocess` at the top if absent. In `_PROVIDER_CALLERS` add `"claude_cli": _call_claude_cli`. In `_PROVIDER_STREAMERS` add a one-shot streamer consistent with the others' signature (inspect `_stream_ollama` first; if signatures are involved, a wrapper that calls `_call_claude_cli` and yields the full text once is fine). Update `_PROVIDER_NAMES` (line 29) to include `'claude_cli'`. In `_model_for` add: `if provider == "claude_cli": return os.environ.get("CLAUDE_CLI_MODEL", "claude-cli")`.

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_llm_claude_cli.py -q` → PASS, then full suite `python -m pytest -q` → all green.

- [ ] **Step 5: Smoke it for real** (this is record-time infrastructure — one live sanity call is mandatory before we depend on it at 2 AM):

```bash
LLM_MODE=live LLM_NO_CACHE=1 LLM_PROVIDER=claude_cli python -c "
from common.llm import complete
print(complete('Reply with exactly: PROVIDER OK'))"
```

Expected: `PROVIDER OK` (any close variant fine). If the CLI hangs or errors, fix flags now (try dropping `--append-system-prompt`, folding system into the prompt).

- [ ] **Step 6: Commit** — `git add common/llm.py tests/test_llm_claude_cli.py && git commit -m "llm: claude_cli record-time provider via headless claude -p"`

---

### Task 2: Real upstream generation + RECORD CHECKPOINT 1 (budget: 90 min)

**Files:**
- Create: `s7_delivery/generate.py`
- Create: `demo/record_run.py`
- Test: `tests/test_generate.py`
- Modify: `s7_delivery/pipeline.py` (`build_state`, line ~165)

**Interfaces:**
- Produces: `generate.assessment(epic: Epic) -> Assessment`, `generate.design(epic: Epic, assessment: Assessment) -> tuple[DesignArtifact, ...]`, `generate.stories(epic: Epic, assessment: Assessment) -> tuple[UserStory, ...]` — exact same shapes `staged.py` returns. `generate.parse_json_block(text: str) -> Any` (fence-stripping JSON parser, reused by Task 3).
- Consumes: `common.llm.complete`, all `s7_delivery.models` types, `pipeline.load_epic`.

- [ ] **Step 1: Failing tests for the parser and one builder** (monkeypatch `complete` — parsing logic is what breaks at 3 AM, so it gets tests; prompts don't):

```python
"""tests/test_generate.py"""
import json
from s7_delivery import generate
from s7_delivery.models import Coverage, Epic, Provenance, Stream

EPIC = Epic(id="EPIC-S7-001", title="t", body="b", source_path="x")

def test_parse_json_block_strips_fences():
    fenced = "```json\n{\"a\": 1}\n```"
    assert generate.parse_json_block(fenced) == {"a": 1}
    assert generate.parse_json_block("{\"a\": 1}") == {"a": 1}

def test_assessment_builds_models(monkeypatch):
    fake = {"tasks": [{"id": "T1", "summary": "s", "stream": "frontend",
                       "coverage": "agentic", "estimate_days": 2.0,
                       "rationale": "r", "depends_on": [], "blocked_by_external": False}],
            "integration_note": "note"}
    monkeypatch.setattr(generate, "complete", lambda *a, **k: json.dumps(fake))
    a = generate.assessment(EPIC)
    assert a.tasks[0].stream is Stream.FRONTEND
    assert a.tasks[0].coverage is Coverage.AGENTIC
    assert a.provenance in (Provenance.LIVE_AI, Provenance.REPLAYED_AI)
```

- [ ] **Step 2: Verify fail** — `python -m pytest tests/test_generate.py -q` → FAIL.

- [ ] **Step 3: Implement `s7_delivery/generate.py`.** Structure (write the three prompts against `crs/EPIC-S7-001.md` content; every `complete()` call passes `json_mode=True` and a stable `cache_key` like `"s7:assess"`, `"s7:design"`, `"s7:stories"` so recordings land at stable paths):

```python
"""Real model-generated upstream artifacts — same shapes staged.py fakes.

Selected by S7_ARTIFACTS=ai; every call goes through common.llm.complete, so
LLM_MODE=record records and LLM_MODE=replay replays. Provenance is REPLAYED_AI
in replay mode, LIVE_AI otherwise — never STAGED, because this module only
returns output a model actually produced.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from common.llm import complete
from s7_delivery.models import (
    AcceptanceCriterion, AssessedTask, Assessment, Coverage, DesignArtifact,
    Epic, Provenance, Stream, Task, UserStory,
)

_SYSTEM = (
    "You are a delivery analyst for MapleSure Insurance's AI-assisted SDLC. "
    "Output strict JSON matching the schema in the task. Invent nothing "
    "beyond the epic; unresolved questions become assumptions, not facts."
)


def _provenance() -> Provenance:
    return Provenance.REPLAYED_AI if os.environ.get("LLM_MODE", "replay") == "replay" else Provenance.LIVE_AI


def parse_json_block(text: str):
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def assessment(epic: Epic) -> Assessment:
    prompt = f"""Epic:\n{epic.body}\n
Break this epic into 6-9 tasks routed across streams
({', '.join(s.value for s in Stream)}). Classify each honestly:
coverage is "agentic" (runs in the automated lane), "ai_assisted_external"
(AI drafts, another team owns), or "manual". At least one task must be
manual or external — a mainframe/system-of-record change others wait on.
JSON schema:
{{"tasks": [{{"id": "T1", "summary": str, "stream": str, "coverage": str,
"estimate_days": float, "rationale": str, "depends_on": [str],
"blocked_by_external": bool}}], "integration_note": str}}"""
    data = parse_json_block(complete(prompt, system=_SYSTEM, json_mode=True, cache_key="s7:assess"))
    tasks = tuple(
        AssessedTask(
            id=t["id"], summary=t["summary"], stream=Stream(t["stream"]),
            coverage=Coverage(t["coverage"]), estimate_days=float(t["estimate_days"]),
            rationale=t.get("rationale", ""), depends_on=tuple(t.get("depends_on", [])),
            blocked_by_external=bool(t.get("blocked_by_external", False)),
        ) for t in data["tasks"]
    )
    return Assessment(epic_id=epic.id, tasks=tasks, integration_note=data.get("integration_note", ""),
                      provenance=_provenance(), generated_at=datetime.now())
```

`design(epic, assessment)`: one call, `cache_key="s7:design"`, asks for JSON `{"dfd": {"title": str, "mermaid": str, "notes": str}, "er": {...}}` where `dfd.mermaid` starts with `flowchart` and `er.mermaid` starts with `erDiagram` (validate with `str.startswith`, raise `ValueError` naming the artifact if not — a broken diagram must fail at record time, not render time). Return two `DesignArtifact`s with ids `"DFD-1"`, `"ER-1"`, kinds `"dfd"`/`"er"`.

`stories(epic, assessment)`: one call, `cache_key="s7:stories"`, asks for 3 stories JSON: `{"stories": [{"id": "US-1", "title": str, "narrative": str, "acceptance": [{"id": "US-1-AC1", "text": str}], "streams": [str], "estimate_points": int, "assumptions": [str], "tasks": [{"id": "US-1-T1", "summary": str, "stream": str, "coverage": str, "estimate_days": float, "satisfies": [str], "depends_on": [str], "owning_team": str|null}]}]}`. **The prompt must require: at least one frontend task with coverage "agentic" whose summary is building the plan-sponsor disability submission page — that task is what the downstream lane runs.** Build `Task`/`UserStory`/`AcceptanceCriterion` exactly as `models.py` defines them (`Task` needs `story_id` and `provenance=_provenance()`).

- [ ] **Step 4: Verify tests pass** — `python -m pytest tests/test_generate.py -q`, then full suite.

- [ ] **Step 5: Wire the selector into `pipeline.py`.** Read `build_state` (line 165) first. Add a source resolver used wherever `staged.assessment()`/`design()`/`stories()` are called today:

```python
def _artifact_source():
    """staged | ai — ai falls back to staged per stage so a missing recording
    degrades to a badged staged artifact instead of a dead demo."""
    if os.environ.get("S7_ARTIFACTS", "staged") != "ai":
        from s7_delivery import staged
        return staged
    from s7_delivery import generate
    return generate
```

At each call site wrap with try/except `(LLMError, ValueError, KeyError)` → log loudly to stderr and fall back to the `staged` equivalent (spec fallback 2). Note the signature difference: `generate.*` takes the epic/assessment as arguments while `staged.*` takes none — adapt at the call site, do not change `staged.py`.

- [ ] **Step 6: Create `demo/record_run.py`** — records upstream in one shot and prints what it got:

```python
"""Record the upstream artifacts via the claude_cli provider.

Usage: LLM_MODE=record LLM_PROVIDER=claude_cli python demo/record_run.py
"""
import sys
from s7_delivery import generate
from s7_delivery.pipeline import load_epic

epic = load_epic()
a = generate.assessment(epic)
print(f"assessment: {len(a.tasks)} tasks, breakdown {a.coverage_breakdown()}")
designs = generate.design(epic, a)
print(f"design: {[d.id for d in designs]}")
stories = generate.stories(epic, a)
for s in stories:
    lane = [t.id for t in s.tasks if t.runs_in_downstream_lane]
    print(f"{s.id}: {len(s.acceptance)} ACs, unsatisfied={s.unsatisfied()}, agentic={lane}")
if not any(t.runs_in_downstream_lane for s in stories for t in s.tasks):
    sys.exit("FATAL: no agentic task for the downstream lane — re-record stories")
```

- [ ] **Step 7: 🔴 RECORD CHECKPOINT 1** — `LLM_MODE=record LLM_PROVIDER=claude_cli python demo/record_run.py`. Inspect the printed output *and read the recorded JSON* under `s7_delivery/cache/llm/` — check the stories read well, no client names leaked, ACs are testable. Re-run to re-roll anything weak (record mode always refreshes). Then verify replay works offline: `LLM_MODE=replay S7_ARTIFACTS=ai python demo/record_run.py` → identical output, no network.

- [ ] **Step 8: Commit** — `git add s7_delivery/generate.py s7_delivery/pipeline.py demo/record_run.py tests/test_generate.py s7_delivery/cache/llm && git commit -m "s7: real recorded upstream — assessment, design, stories via claude_cli"`

---

### Task 3: Downstream lane + RECORD CHECKPOINT 2 (budget: 2 h)

**Files:**
- Create: `s7_delivery/downstream.py`
- Create: `demo/record_downstream.py`
- Test: `tests/test_downstream.py`
- Generated at record time: `artifacts/EPIC-S7-001/downstream/` (app files, test file, `events.jsonl`, `review.json`) — **committed**, they are demo material.

**Interfaces:**
- Consumes: `generate.parse_json_block`, `common.llm.complete`, `models.Task`/`UserStory`.
- Produces: `downstream.run_lane(story: UserStory, task: Task, root: Path) -> LaneResult` where `LaneResult` has `ok: bool`, `app_dir: Path`, `events_path: Path`, `test_output: str`, `review: dict`. Events JSONL lines: `{"ts": float, "agent": "developer"|"tester"|"reviewer"|"system", "action": str, "artifact": str|null, "status": "start"|"done"|"fail"}` — **this line format is the contract Task 4's console animates.**

- [ ] **Step 1: Failing test** (monkeypatch `complete`; pytest-on-generated-files runs for real):

```python
"""tests/test_downstream.py"""
import json
from pathlib import Path
from s7_delivery import downstream
from s7_delivery.models import (AcceptanceCriterion, Coverage, Provenance, Stream, Task, UserStory)

TASK = Task(id="US-1-T1", story_id="US-1", summary="submission page", stream=Stream.FRONTEND,
            coverage=Coverage.AGENTIC, estimate_days=2.0, provenance=Provenance.REPLAYED_AI,
            satisfies=("US-1-AC1",))
STORY = UserStory(id="US-1", title="t", narrative="n",
                  acceptance=(AcceptanceCriterion("US-1-AC1", "sponsor can submit claim form"),),
                  streams=(Stream.FRONTEND,), estimate_points=3,
                  provenance=Provenance.REPLAYED_AI, tasks=(TASK,))

def _fake_complete(prompt, **kwargs):
    key = kwargs.get("cache_key", "")
    if "developer" in key:
        return json.dumps({"files": [{"path": "index.html",
            "content": "<html><form id='claim-form'><input id='policy-number'></form></html>"}]})
    if "tester" in key:
        return json.dumps({"files": [{"path": "test_app.py", "content":
            "from pathlib import Path\n\ndef test_form_present():\n"
            "    html = (Path(__file__).parent / 'index.html').read_text()\n"
            "    assert 'claim-form' in html\n"}]})
    return json.dumps({"verdict": "pass", "criteria": [{"id": "US-1-AC1", "met": True}], "notes": []})

def test_run_lane_produces_app_events_and_green_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(downstream, "complete", _fake_complete)
    result = downstream.run_lane(STORY, TASK, root=tmp_path)
    assert result.ok
    assert (result.app_dir / "index.html").exists()
    events = [json.loads(l) for l in result.events_path.read_text().splitlines()]
    agents = {e["agent"] for e in events}
    assert {"developer", "tester", "reviewer"} <= agents
    assert result.review["verdict"] == "pass"
```

- [ ] **Step 2: Verify fail**, then implement `s7_delivery/downstream.py`:

```python
"""Build → test → review for one AGENTIC task. Happy path, hard-capped.

Three role-labelled calls (Developer, Tester, Reviewer) — visible agent roles
over plain orchestration, per the 2026-08-04 'not going agentic' decision.
Every artifact lands under root/; events.jsonl is the console's animation feed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from common.llm import complete
from s7_delivery.generate import parse_json_block
from s7_delivery.models import Task, UserStory

_SYSTEM = (
    "You are an agent in MapleSure Insurance's delivery pipeline. Output "
    "strict JSON per the task schema. Plain HTML/CSS/JS and Python stdlib "
    "only — no CDNs, no frameworks, no network calls."
)


@dataclass
class LaneResult:
    ok: bool
    app_dir: Path
    events_path: Path
    test_output: str
    review: dict


class _Events:
    def __init__(self, path: Path):
        self.path = path
        path.write_text("")
    def emit(self, agent: str, action: str, artifact: str | None = None, status: str = "done"):
        line = {"ts": time.time(), "agent": agent, "action": action,
                "artifact": artifact, "status": status}
        with self.path.open("a") as f:
            f.write(json.dumps(line) + "\n")


def _write_files(data: dict, dest: Path) -> list[str]:
    names = []
    for f in data["files"]:
        rel = Path(f["path"]).name  # flatten: no traversal, demo app is flat
        (dest / rel).write_text(f["content"])
        names.append(rel)
    return names


def run_lane(story: UserStory, task: Task, root: Path) -> LaneResult:
    app_dir = root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    ev = _Events(root / "events.jsonl")

    ev.emit("developer", f"picked up {task.id}: {task.summary}", status="start")
    dev = parse_json_block(complete(_developer_prompt(story, task), system=_SYSTEM,
                                    json_mode=True, cache_key="s7:downstream:developer"))
    files = _write_files(dev, app_dir)
    ev.emit("developer", "wrote application code", artifact=", ".join(files))

    ev.emit("tester", "writing tests against acceptance criteria", status="start")
    tst = parse_json_block(complete(_tester_prompt(story, task, files, app_dir), system=_SYSTEM,
                                    json_mode=True, cache_key="s7:downstream:tester"))
    test_files = _write_files(tst, app_dir)
    ev.emit("tester", "wrote tests", artifact=", ".join(test_files))

    ev.emit("tester", "running pytest", status="start")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", str(app_dir)],
                          capture_output=True, text=True, timeout=120)
    green = proc.returncode == 0
    ev.emit("tester", "tests green" if green else "tests FAILED",
            artifact=test_files[0] if test_files else None,
            status="done" if green else "fail")

    ev.emit("reviewer", "checking output against acceptance criteria", status="start")
    review = parse_json_block(complete(_reviewer_prompt(story, task, app_dir, proc.stdout),
                                       system=_SYSTEM, json_mode=True,
                                       cache_key="s7:downstream:reviewer"))
    (root / "review.json").write_text(json.dumps(review, indent=2))
    verdict_ok = review.get("verdict") == "pass"
    ev.emit("reviewer", f"verdict: {review.get('verdict')}", artifact="review.json",
            status="done" if verdict_ok else "fail")

    ok = green and verdict_ok
    ev.emit("system", "lane complete" if ok else "lane finished with failures",
            status="done" if ok else "fail")
    return LaneResult(ok=ok, app_dir=app_dir, events_path=ev.path,
                      test_output=proc.stdout[-2000:], review=review)
```

The three `_*_prompt` functions, concretely:
- `_developer_prompt(story, task)` — includes story narrative + ACs + task summary; asks for `{"files": [{"path", "content"}]}` containing exactly `index.html` (single-page MapleSure disability claim submission: policy number, member id, a "look up member" button that fills mock member details **from a JS object in the page, no fetch**, claim details fields, a file-upload input allowing multiple files, submit → confirmation panel with a reference number and status "Received"). Styling inline, professional, works by double-clicking the file.
- `_tester_prompt(story, task, files, app_dir)` — passes the *actual generated* `index.html` content (read it back); asks for `{"files": [{"path": "test_app.py", "content": ...}]}` with 3–5 pytest tests that read `index.html` from `Path(__file__).parent` and assert the ACs' happy path structurally (required ids present, upload input has `multiple`, confirmation markup present). No browser, no server.
- `_reviewer_prompt(story, task, app_dir, test_output)` — passes ACs + generated files + pytest output; asks for `{"verdict": "pass"|"fail", "criteria": [{"id", "met", "note"}], "notes": [...]}`.

- [ ] **Step 3: Tests pass** — `python -m pytest tests/test_downstream.py -q`, then full suite.

- [ ] **Step 4: Create `demo/record_downstream.py`:**

```python
"""Record the downstream lane for the first AGENTIC task.

Usage: LLM_MODE=record LLM_PROVIDER=claude_cli python demo/record_downstream.py
"""
import sys
from pathlib import Path
from s7_delivery import generate
from s7_delivery.downstream import run_lane
from s7_delivery.pipeline import load_epic

epic = load_epic()
a = generate.assessment(epic)          # replayed from Task 2's recordings
stories = generate.stories(epic, a)
picks = [(s, t) for s in stories for t in s.tasks if t.runs_in_downstream_lane]
if not picks:
    sys.exit("FATAL: no agentic task")
story, task = picks[0]
result = run_lane(story, task, root=Path("artifacts") / epic.id / "downstream")
print(f"ok={result.ok} app={result.app_dir} verdict={result.review.get('verdict')}")
print(result.test_output)
sys.exit(0 if result.ok else 1)
```

- [ ] **Step 5: 🔴 RECORD CHECKPOINT 2** — `LLM_MODE=record LLM_PROVIDER=claude_cli python demo/record_downstream.py`. The upstream calls replay (already recorded); only the three downstream calls go live. If tests come back red or the app is ugly, re-run (record refreshes). **Then open `artifacts/EPIC-S7-001/downstream/app/index.html` in a browser and click through the happy path yourself.** Verify replay: `LLM_MODE=replay python demo/record_downstream.py` → same result offline.

- [ ] **Step 6: Commit** — `git add s7_delivery/downstream.py demo/record_downstream.py tests/test_downstream.py s7_delivery/cache/llm artifacts && git commit -m "s7: downstream lane — developer/tester/reviewer, recorded, tests green"`

> **From this commit on, the demo material is safe.** Everything after is presentation. If the night collapses here, the story is still: real recorded upstream + one real task through build/test/review + a working generated app opened by hand.

---

### Task 4: Console — five-gate overview, downstream lanes, activity feed (budget: 2.5 h)

**Files:**
- Modify: `apps/console/server.py`, `apps/console/static/index.html`, `apps/console/static/app.js`, `apps/console/static/styles.css`

**Interfaces:**
- Consumes: `pipeline.build_state`/`to_payload` (with `S7_ARTIFACTS=ai`), `artifacts/EPIC-S7-001/downstream/events.jsonl` + `review.json` + `app/`, existing gate decide endpoint in `server.py`.
- Produces: `GET /api/downstream` → `{"events": [...], "review": {...}, "app_available": bool}`; `POST /api/release` body `{"decision": "approved", "reviewer": str}` → in-memory release-gate state, included in the main payload as `release_gate`; static serving of `artifacts/EPIC-S7-001/downstream/app/` at `/generated-app/`; payload gains `gates`: a list of five `{"id", "label", "status"}`.

**Read `apps/console/server.py` and the first ~100 lines of `app.js` before editing — follow their existing routing/render patterns exactly.**

- [ ] **Step 1: Server endpoints.** In `server.py`: add the downstream route (read the JSONL into a list, tolerate the file being absent → `{"events": [], "app_available": false}`); serve `/generated-app/<file>` from the artifacts app dir with correct content-type; hold `release_gate` in module state mirroring how the existing design gate decision is held; compute `gates` server-side:

| Gate | Label | Status rule |
|---|---|---|
| G0 | Intake complete | `approved` once the epic parsed |
| G1 | Design sign-off | mirrors the existing human gate decision |
| G2 | AC coverage | `approved` if every story's `unsatisfied()` is empty, else `pending` |
| G3 | Independent review | from `review.json` verdict: pass→`approved`, fail→`rejected`, absent→`pending` |
| G4 | Release | mirrors `release_gate`, only actionable once G3 approved |

- [ ] **Step 2: Overview screen.** New first view in `index.html`/`app.js`: five gate chips left-to-right connected by a line, each showing status color (existing palette), each clickable → scrolls/switches to that gate's stage view. A "◀ overview" affordance on every stage view ties back (the call's instruction: every deep-dive links to the overview).

- [ ] **Step 3: Downstream view.** After the stories view: three vertical lanes labelled **Developer agent 1/2/3**. Lane 1 animates from the events feed — render each event as a feed row (`agent`, `action`, `artifact`), appearing on a timer (~1.2 s apart, `setInterval` walking the array). Provenance badge on the panel: `REPLAYED_AI — recorded run`. Lanes 2–3 show queued tasks and a single button **"Run remaining lanes"** → both fill instantly with a summary row ("completed — same recorded lane"); then an **Integration** node lights, then the test row (green from events), then G4 unlocks: **Approve release** button → POST `/api/release` → **"Open application"** button appears, target `/generated-app/index.html`, new tab.

- [ ] **Step 4: Manual test script** (no DOM unit tests tonight — the pytest suite guards the API): run `S7_ARTIFACTS=ai LLM_MODE=replay demo/run_console.sh`; walk: overview all-pending → epic → assessment → design → **approve G1** → stories → downstream animation → run remaining lanes → approve release → app opens. Also verify a *rejection* at G1 still locks stories (existing behavior must not regress), and `curl -s localhost:PORT/api/downstream | python -m json.tool` returns events.

- [ ] **Step 5: Run full pytest suite** — green — then commit: `git add apps/console && git commit -m "console: five-gate overview, downstream agent lanes, release gate, generated app"`

---

### Task 5: Rehearsal, video backup, teleprompt patch (budget: 60 min + one full pass)

**Files:**
- Create: `docs/demo-script-2026-08-07.md` (the beat list from the spec § The demo beat, expanded with exactly what to click and what sentence accompanies each click — including the tie-back lines and the "one lane shown, others identical" line, and the answer if asked about estimates: "placeholder today; historical delivery data is the grounding source")
- No repo changes beyond that.

- [ ] **Step 1: Fresh-environment replay proof** — in a clean shell with no API-related env vars: `git stash list` empty of needed files, then `S7_ARTIFACTS=ai LLM_MODE=replay demo/run_console.sh`; full click-through. This is the exact demo-day configuration.
- [ ] **Step 2: Screen-record one clean pass** (QuickTime, `⌘⇧5`) end to end, save outside the repo (`~/Desktop/s7-demo-backup-2026-08-07.mov`) — Sita's backup instruction; it must not be committed (size + it shows the local machine).
- [ ] **Step 3: Rehearse the talk track once against the clock** — target under 10 minutes.
- [ ] **Step 4: Commit the script** — `git add docs/demo-script-2026-08-07.md && git commit -m "docs: demo script for 2026-08-07 dry run"`
- [ ] **Step 5: Set up the fallback** — keep a terminal tab pre-typed with `python demo/record_downstream.py` under `LLM_MODE=replay` (CLI transcript fallback) and the backup video open in Finder.

---

## Self-review notes

- **Spec coverage:** provider → Task 1; recorded upstream → Task 2; downstream lane + app → Task 3; overview/activity/lanes/release → Task 4; insurance/backup → Task 5. Staged-badge fallback → Task 2 Step 5 try/except; lanes 2–3 honesty labels → Task 4 Step 3 wording.
- **Type consistency:** `run_lane(story, task, root) -> LaneResult` used identically in Tasks 3–4; events JSONL schema stated once in Task 3 interfaces and consumed verbatim in Task 4; `generate.assessment(epic)`/`design(epic, a)`/`stories(epic, a)` consistent across Tasks 2–3.
- **Known risk:** exact `claude -p` flags (`--append-system-prompt`) and `Usage` constructor field names are verified live in Task 1 Steps 3/5 before anything depends on them.
