# Governed Factory — Plan 1: Artifact Plane, Ledger, Contract, Gates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the artifact plane with a hash-chained provenance ledger, extend the stage contract with story-quality and downstream fields, and implement gates G0 (intake), G2 (story quality) and G3 (independent verify).

**Architecture:** Every stage output becomes a JSON envelope (`meta` + `body`) at `artifacts/<epic>/<stage>/<id>.json`, hashed with SHA-256 and pointing at its upstream artifacts via `derived_from` — staleness is a hash mismatch along those pointers. `artifacts/ledger.jsonl` is append-only and hash-chained (each line carries the SHA-256 of the previous raw line). Gates are pure functions returning named failures; G3 writes a verdict artifact. Spec: `docs/superpowers/specs/2026-08-06-governed-factory-design.md`.

**Tech Stack:** Python 3.12+ stdlib only (`hashlib`, `json`, `dataclasses`, `pathlib`), pytest. No new dependencies.

## Global Constraints

- No real client data; the demo insurer is fictional **"MapleSure Insurance"** (CLAUDE.md hard rules 1–2).
- Plain Python + files; no cloud services, no Docker, no new pip dependencies (hard rule 4).
- All tests run offline with no API key.
- `artifacts/` is **gitignored** runtime output; committed inputs live in `crs/`, `s7_delivery/rules/`, `s7_delivery/skills/`.
- G3 is rule-based and must be labelled `"rule-based-verifier"` in its output — never presented as AI.
- All contract changes are **additive**: the existing 60 tests must stay green after every task.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- The existing style: modules document *why* in docstrings; follow `s7_delivery/models.py`'s tone.

## File Structure

- Create: `s7_delivery/artifacts.py` — envelope read/write, canonical hashing, staleness (one responsibility: the plane)
- Create: `s7_delivery/ledger.py` — append-only hash-chained JSONL (one responsibility: the chain)
- Create: `s7_delivery/gates.py` — G0 + G2 pure checks returning `GateFailure`s
- Create: `s7_delivery/verifier.py` — G3 cross-checks, writes verdict artifact
- Modify: `s7_delivery/models.py` — additive fields + new dataclasses
- Modify: `s7_delivery/staged.py` — staged stories gain the story-quality fields
- Modify: `s7_delivery/pipeline.py` — `_story_payload` exposes the new fields
- Modify: `.gitignore` — add `artifacts/`
- Test: `tests/test_artifacts.py`, `tests/test_ledger.py`, `tests/test_gates.py`, `tests/test_verifier.py`; extend `tests/test_models.py`

---

### Task 1: Canonical hashing and the artifact envelope

**Files:**
- Create: `s7_delivery/artifacts.py`
- Test: `tests/test_artifacts.py`

**Interfaces:**
- Consumes: nothing new (stdlib only).
- Produces: `content_hash(body: dict) -> str` (returns `"sha256:<hex>"`), `canonical_json(body: dict) -> str`, `ArtifactError(Exception)`, `artifact_path(root: Path, epic_id: str, stage: str, artifact_id: str) -> Path`, `write_envelope(path: Path, meta: dict, body: dict) -> None`, `read_artifact(path: Path) -> dict` (returns the envelope; raises `ArtifactError` on hash mismatch). Later tasks build `write_artifact` on top of these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_artifacts.py
"""The artifact plane: envelopes, hashing, provenance pointers, staleness."""

import json
from pathlib import Path

import pytest

from s7_delivery import artifacts


def test_content_hash_is_stable_across_key_order():
    a = artifacts.content_hash({"b": 1, "a": [1, 2]})
    b = artifacts.content_hash({"a": [1, 2], "b": 1})
    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_content_hash_changes_when_body_changes():
    assert artifacts.content_hash({"a": 1}) != artifacts.content_hash({"a": 2})


def test_artifact_path_is_deterministic(tmp_path: Path):
    p = artifacts.artifact_path(tmp_path, "EPIC-S7-001", "assess", "assessment")
    assert p == tmp_path / "EPIC-S7-001" / "assess" / "assessment.json"


def test_read_artifact_round_trips(tmp_path: Path):
    path = artifacts.artifact_path(tmp_path, "EPIC-S7-001", "assess", "assessment")
    body = {"tasks": [1, 2, 3]}
    meta = {"artifact_id": "assessment", "content_hash": artifacts.content_hash(body)}
    artifacts.write_envelope(path, meta, body)
    envelope = artifacts.read_artifact(path)
    assert envelope["body"] == body
    assert envelope["meta"]["artifact_id"] == "assessment"


def test_read_artifact_rejects_tampered_body(tmp_path: Path):
    path = artifacts.artifact_path(tmp_path, "EPIC-S7-001", "assess", "assessment")
    body = {"estimate": 10}
    meta = {"artifact_id": "assessment", "content_hash": artifacts.content_hash(body)}
    artifacts.write_envelope(path, meta, body)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["body"]["estimate"] = 5  # the quiet edit the hash exists to catch
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(artifacts.ArtifactError, match="hash"):
        artifacts.read_artifact(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_artifacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's7_delivery.artifacts'` (or ImportError).

- [ ] **Step 3: Write the implementation**

```python
# s7_delivery/artifacts.py
"""The artifact plane: stage outputs as hashed JSON envelopes at deterministic paths.

Every stage writes an envelope — a `meta` header plus the serialized `body` —
to `artifacts/<epic-id>/<stage>/<artifact-id>.json`. The header carries a
SHA-256 hash of the body and `derived_from` pointers at the upstream artifacts
it was built from. That one decision buys three features at once: provenance
is a chain rather than a claim, staleness is a hash comparison, and a stage
whose valid output already exists can skip — which is what makes an
interrupted demo resumable (hard rule 5).

The hash covers the *canonical* JSON serialization (sorted keys, tight
separators) so that dict ordering can never make identical content look
different.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ARTIFACTS_ENV = "S7_ARTIFACTS_DIR"
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "artifacts"


class ArtifactError(Exception):
    """Raised when an artifact is missing, malformed, or fails its hash."""


def artifacts_root() -> Path:
    """The plane's root. Env-overridable so tests and demos can relocate it."""
    return Path(os.environ.get(ARTIFACTS_ENV, str(_DEFAULT_ROOT)))


def canonical_json(body: dict) -> str:
    """One serialization per value, regardless of insertion order."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(body: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def artifact_path(root: Path, epic_id: str, stage: str, artifact_id: str) -> Path:
    return root / epic_id / stage / f"{artifact_id}.json"


def write_envelope(path: Path, meta: dict, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "body": body}, indent=2), encoding="utf-8")


def read_artifact(path: Path) -> dict:
    """Load an envelope, refusing silently corrupted or edited bodies."""
    if not path.exists():
        raise ArtifactError(f"No artifact at {path}")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Artifact at {path} is not valid JSON: {exc}") from exc
    meta = envelope.get("meta", {})
    body = envelope.get("body")
    if body is None or "content_hash" not in meta:
        raise ArtifactError(f"Artifact at {path} is missing meta.content_hash or body")
    actual = content_hash(body)
    if actual != meta["content_hash"]:
        raise ArtifactError(
            f"Artifact at {path} fails its content hash: "
            f"recorded {meta['content_hash']}, computed {actual}"
        )
    return envelope
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_artifacts.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/artifacts.py tests/test_artifacts.py
git commit -m "feat: artifact envelopes with canonical SHA-256 hashing

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: The hash-chained ledger

**Files:**
- Create: `s7_delivery/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: nothing from other tasks (stdlib only).
- Produces: `LedgerError(Exception)`, `ledger_path(root: Path) -> Path`, `append_entry(root: Path, entry: dict) -> dict` (returns the entry as written, including `"prev"`), `verify_chain(root: Path) -> int` (entry count; raises `LedgerError` naming the line on a break), `read_entries(root: Path) -> list[dict]` (verifies first). Task 3 calls `append_entry`; the healing loop (Plan 3) reads via `read_entries`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger.py
"""The provenance ledger: append-only, hash-chained, tamper-evident."""

import json
from pathlib import Path

import pytest

from s7_delivery import ledger


def test_append_links_each_entry_to_the_previous_line(tmp_path: Path):
    first = ledger.append_entry(tmp_path, {"event": "write", "path": "a.json"})
    second = ledger.append_entry(tmp_path, {"event": "write", "path": "b.json"})
    assert first["prev"] == "genesis"
    assert second["prev"].startswith("sha256:")
    assert first["prev"] != second["prev"]


def test_verify_chain_passes_on_untouched_ledger(tmp_path: Path):
    for i in range(3):
        ledger.append_entry(tmp_path, {"event": "write", "path": f"{i}.json"})
    assert ledger.verify_chain(tmp_path) == 3


def test_verify_chain_names_the_edited_line(tmp_path: Path):
    for i in range(3):
        ledger.append_entry(tmp_path, {"event": "write", "path": f"{i}.json"})
    path = ledger.ledger_path(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["path"] = "edited.json"  # rewrite history
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match="line 3"):
        ledger.verify_chain(tmp_path)


def test_read_entries_returns_parsed_entries_in_order(tmp_path: Path):
    ledger.append_entry(tmp_path, {"event": "write", "path": "a.json"})
    ledger.append_entry(tmp_path, {"event": "verify", "path": "a.json"})
    events = [e["event"] for e in ledger.read_entries(tmp_path)]
    assert events == ["write", "verify"]


def test_empty_ledger_verifies_as_zero(tmp_path: Path):
    assert ledger.verify_chain(tmp_path) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's7_delivery.ledger'`.

- [ ] **Step 3: Write the implementation**

```python
# s7_delivery/ledger.py
"""Append-only provenance ledger, hash-chained so edits to history are visible.

One JSONL line per artifact event. Each line carries `prev`: the SHA-256 of
the previous raw line (`"genesis"` for the first). Editing any line changes
its hash, which breaks the recorded `prev` of the line after it — so
tampering is evident with zero infrastructure, and `verify_chain` can name
the exact line. This is the append-only SHA-256 tracking the feature list
asks for, made literal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"
GENESIS = "genesis"


class LedgerError(Exception):
    """Raised when the ledger chain is broken or a line is malformed."""


def ledger_path(root: Path) -> Path:
    return root / LEDGER_NAME


def _line_hash(raw_line: str) -> str:
    return "sha256:" + hashlib.sha256(raw_line.encode("utf-8")).hexdigest()


def append_entry(root: Path, entry: dict) -> dict:
    """Append one event, linked to the current last line."""
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prev = _line_hash(lines[-1]) if lines else GENESIS
    full = {**entry, "prev": prev}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(full, sort_keys=True) + "\n")
    return full


def verify_chain(root: Path) -> int:
    """Walk the chain; raise naming the first line that does not link."""
    path = ledger_path(root)
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    prev = GENESIS
    for number, raw in enumerate(lines, start=1):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"Ledger line {number} is not valid JSON: {exc}") from exc
        if entry.get("prev") != prev:
            raise LedgerError(
                f"Ledger chain broken at line {number}: "
                f"recorded prev {entry.get('prev')!r} does not match the line before it"
            )
        prev = _line_hash(raw)
    return len(lines)


def read_entries(root: Path) -> list[dict]:
    """Parsed entries, oldest first. Verifies the chain before returning."""
    verify_chain(root)
    path = ledger_path(root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/ledger.py tests/test_ledger.py
git commit -m "feat: append-only hash-chained provenance ledger

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `write_artifact` — envelopes, ledger, and skip-if-valid

**Files:**
- Modify: `s7_delivery/artifacts.py`
- Test: `tests/test_artifacts.py` (append)

**Interfaces:**
- Consumes: `ledger.append_entry` (Task 2), Task 1's helpers.
- Produces: `write_artifact(root: Path, *, epic_id: str, stage: str, artifact_id: str, body: dict, producer: str, provenance: str, derived_from: tuple[str, ...] = ()) -> Path`, `derived_ref(root: Path, path: Path) -> str` (formats `"sha256:<hex> <path relative to root>"`), `has_valid_artifact(root: Path, epic_id: str, stage: str, artifact_id: str) -> bool`. G3 (Task 8) and every later stage write through `write_artifact`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_artifacts.py`)

```python
from s7_delivery import ledger


def test_write_artifact_builds_meta_and_appends_to_ledger(tmp_path: Path):
    path = artifacts.write_artifact(
        tmp_path,
        epic_id="EPIC-S7-001",
        stage="assess",
        artifact_id="assessment",
        body={"tasks": 12},
        producer="pipeline",
        provenance="staged",
    )
    envelope = artifacts.read_artifact(path)
    meta = envelope["meta"]
    assert meta["stage"] == "assess"
    assert meta["epic_id"] == "EPIC-S7-001"
    assert meta["producer"] == "pipeline"
    assert meta["provenance"] == "staged"
    assert meta["content_hash"] == artifacts.content_hash({"tasks": 12})
    assert meta["derived_from"] == []
    assert meta["verified"] is None
    assert meta["created_at"]  # ISO timestamp, presence is enough here
    entries = ledger.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["path"] == "EPIC-S7-001/assess/assessment.json"
    assert entries[0]["hash"] == meta["content_hash"]


def test_derived_ref_and_derived_from_round_trip(tmp_path: Path):
    upstream = artifacts.write_artifact(
        tmp_path, epic_id="E", stage="assess", artifact_id="assessment",
        body={"v": 1}, producer="pipeline", provenance="staged",
    )
    ref = artifacts.derived_ref(tmp_path, upstream)
    downstream = artifacts.write_artifact(
        tmp_path, epic_id="E", stage="stories", artifact_id="US-1",
        body={"story": "x"}, producer="pipeline", provenance="staged",
        derived_from=(ref,),
    )
    meta = artifacts.read_artifact(downstream)["meta"]
    assert meta["derived_from"] == [ref]
    assert ref.endswith("E/assess/assessment.json")


def test_has_valid_artifact_false_when_absent_true_after_write(tmp_path: Path):
    assert not artifacts.has_valid_artifact(tmp_path, "E", "assess", "assessment")
    artifacts.write_artifact(
        tmp_path, epic_id="E", stage="assess", artifact_id="assessment",
        body={"v": 1}, producer="pipeline", provenance="staged",
    )
    assert artifacts.has_valid_artifact(tmp_path, "E", "assess", "assessment")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_artifacts.py -v`
Expected: the three new tests FAIL with `AttributeError: module 's7_delivery.artifacts' has no attribute 'write_artifact'`; the Task 1 tests still PASS.

- [ ] **Step 3: Write the implementation** (append to `s7_delivery/artifacts.py`)

```python
from datetime import UTC, datetime

from s7_delivery import ledger


def write_artifact(
    root: Path,
    *,
    epic_id: str,
    stage: str,
    artifact_id: str,
    body: dict,
    producer: str,
    provenance: str,
    derived_from: tuple[str, ...] = (),
) -> Path:
    """Write one stage output to the plane and record it in the ledger.

    `derived_from` entries come from `derived_ref` — hash plus relative path —
    so the artifact records exactly which upstream *content* it was built
    from, not merely which file name.
    """
    path = artifact_path(root, epic_id, stage, artifact_id)
    meta = {
        "artifact_id": artifact_id,
        "stage": stage,
        "epic_id": epic_id,
        "producer": producer,
        "provenance": provenance,
        "created_at": datetime.now(UTC).isoformat(),
        "content_hash": content_hash(body),
        "derived_from": list(derived_from),
        "verified": None,
    }
    write_envelope(path, meta, body)
    ledger.append_entry(
        root,
        {
            "event": "write",
            "path": str(path.relative_to(root)),
            "hash": meta["content_hash"],
            "stage": stage,
            "epic_id": epic_id,
            "producer": producer,
            "provenance": provenance,
            "at": meta["created_at"],
        },
    )
    return path


def derived_ref(root: Path, path: Path) -> str:
    """A provenance pointer: the upstream artifact's hash plus its plane path."""
    envelope = read_artifact(path)
    return f'{envelope["meta"]["content_hash"]} {path.relative_to(root)}'


def has_valid_artifact(root: Path, epic_id: str, stage: str, artifact_id: str) -> bool:
    """True when a well-formed, hash-valid artifact already exists.

    The resume story: a stage checks this and skips itself when its output is
    already on the plane.
    """
    path = artifact_path(root, epic_id, stage, artifact_id)
    if not path.exists():
        return False
    try:
        read_artifact(path)
    except ArtifactError:
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_artifacts.py tests/test_ledger.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/artifacts.py tests/test_artifacts.py
git commit -m "feat: write_artifact — plane writes with provenance and ledger events

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Staleness detection

**Files:**
- Modify: `s7_delivery/artifacts.py`
- Test: `tests/test_artifacts.py` (append)

**Interfaces:**
- Consumes: Task 3's `write_artifact` / `derived_ref`.
- Produces: `stale_reasons(root: Path, path: Path) -> tuple[str, ...]` — empty means fresh; each reason is a human-readable string naming the upstream path. Gate 4 (Plan 2) refuses release on any non-empty result; the console (Plan 4) flags them.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_artifacts.py`)

```python
def _write_pair(tmp_path: Path):
    """An upstream assessment and a story derived from it."""
    upstream = artifacts.write_artifact(
        tmp_path, epic_id="E", stage="assess", artifact_id="assessment",
        body={"v": 1}, producer="pipeline", provenance="staged",
    )
    ref = artifacts.derived_ref(tmp_path, upstream)
    downstream = artifacts.write_artifact(
        tmp_path, epic_id="E", stage="stories", artifact_id="US-1",
        body={"story": "x"}, producer="pipeline", provenance="staged",
        derived_from=(ref,),
    )
    return upstream, downstream


def test_fresh_artifact_has_no_stale_reasons(tmp_path: Path):
    _, downstream = _write_pair(tmp_path)
    assert artifacts.stale_reasons(tmp_path, downstream) == ()


def test_changed_upstream_marks_downstream_stale(tmp_path: Path):
    _, downstream = _write_pair(tmp_path)
    artifacts.write_artifact(  # upstream regenerated with different content
        tmp_path, epic_id="E", stage="assess", artifact_id="assessment",
        body={"v": 2}, producer="pipeline", provenance="staged",
    )
    reasons = artifacts.stale_reasons(tmp_path, downstream)
    assert len(reasons) == 1
    assert "E/assess/assessment.json" in reasons[0]
    assert "stale" in reasons[0]


def test_missing_upstream_is_reported_not_ignored(tmp_path: Path):
    upstream, downstream = _write_pair(tmp_path)
    upstream.unlink()
    reasons = artifacts.stale_reasons(tmp_path, downstream)
    assert len(reasons) == 1
    assert "missing" in reasons[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_artifacts.py -v`
Expected: three new FAILs with `AttributeError: ... no attribute 'stale_reasons'`.

- [ ] **Step 3: Write the implementation** (append to `s7_delivery/artifacts.py`)

```python
def stale_reasons(root: Path, path: Path) -> tuple[str, ...]:
    """Why this artifact can no longer be trusted, if it cannot.

    An artifact is stale when any upstream it recorded in `derived_from` has
    since changed (hash mismatch) or vanished. Empty tuple means fresh.
    Reported rather than raised: staleness is a state the UI shows and Gate 4
    enforces, not an exception.
    """
    envelope = read_artifact(path)
    reasons: list[str] = []
    for ref in envelope["meta"].get("derived_from", []):
        recorded_hash, _, rel = ref.partition(" ")
        upstream = root / rel
        if not upstream.exists():
            reasons.append(f"missing upstream {rel}")
            continue
        current = read_artifact(upstream)["meta"]["content_hash"]
        if current != recorded_hash:
            reasons.append(f"stale against {rel}: upstream content changed")
    return tuple(reasons)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_artifacts.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/artifacts.py tests/test_artifacts.py
git commit -m "feat: staleness detection via derived_from hash comparison

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Contract additions in `models.py`

**Files:**
- Modify: `s7_delivery/models.py`
- Test: `tests/test_models.py` (append)

**Interfaces:**
- Consumes: existing `models.py` types.
- Produces: `UserStory` gains `purpose: str = ""`, `impacts: tuple[str, ...] = ()`, `feature_flag: str = ""`, `rollback_plan: str = ""`. `Task` gains `task_type: str = "code"`, `patch_path: str | None = None`. New frozen dataclasses: `Verdict(epic_id: str, passed: bool, findings: tuple[str, ...], checked_by: str, checked_at: datetime)`, `CalibrationRecord(epic_id: str, predicted_days: dict[str, float], actual_days: dict[str, float], error_pct: float, factors: dict[str, float])`, `SkillAmendment(skill: str, version: int, reason_code: str, text: str, triggered_by: tuple[str, ...], created_at: datetime)`, `DownstreamResult(task_id: str, stage: str, ok: bool, detail: str, output: str, provenance: Provenance)`. Plans 2–3 consume these; G2/G3 (Tasks 7–8) consume the story fields.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`, following its existing style)

```python
from datetime import UTC, datetime

from s7_delivery.models import (
    CalibrationRecord,
    DownstreamResult,
    Provenance,
    SkillAmendment,
    Verdict,
)


def test_user_story_quality_fields_default_empty(story_kwargs):
    story = UserStory(**story_kwargs)
    assert story.purpose == ""
    assert story.impacts == ()
    assert story.feature_flag == ""
    assert story.rollback_plan == ""


def test_task_gains_type_and_patch_path(task_kwargs):
    task = Task(**task_kwargs)
    assert task.task_type == "code"
    assert task.patch_path is None


def test_verdict_carries_the_honesty_label():
    verdict = Verdict(
        epic_id="EPIC-S7-001",
        passed=False,
        findings=("story US-2 covers no assessment stream",),
        checked_by="rule-based-verifier",
        checked_at=datetime.now(UTC),
    )
    assert verdict.checked_by == "rule-based-verifier"
    assert not verdict.passed


def test_new_contract_types_construct():
    CalibrationRecord(
        epic_id="EPIC-S7-001",
        predicted_days={"frontend": 10.0},
        actual_days={"frontend": 14.0},
        error_pct=40.0,
        factors={"frontend": 1.4},
    )
    SkillAmendment(
        skill="stories",
        version=2,
        reason_code="missing_rollback_plan",
        text="Every story must state a rollback plan.",
        triggered_by=("ledger:14",),
        created_at=datetime.now(UTC),
    )
    DownstreamResult(
        task_id="T-1",
        stage="test",
        ok=True,
        detail="pytest green",
        output="3 passed",
        provenance=Provenance.STAGED,
    )
```

Note for the implementer: `tests/test_models.py` already constructs `UserStory` and `Task`; reuse its existing fixtures/helpers for `story_kwargs` / `task_kwargs`, or build the kwargs inline exactly as neighbouring tests in that file do — read the file first and match it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py -v`
Expected: new tests FAIL (`ImportError` for `Verdict` etc.); all pre-existing tests PASS.

- [ ] **Step 3: Write the implementation** (modify `s7_delivery/models.py`)

Append to `UserStory` (after `tasks: tuple[Task, ...] = ()`):

```python
    purpose: str = ""
    """Why this story exists — the G2 story-quality standard requires it."""
    impacts: tuple[str, ...] = ()
    """Components and behaviours this story touches."""
    feature_flag: str = ""
    """The flag the change ships behind. Empty fails G2 once decomposed."""
    rollback_plan: str = ""
    """How the change is backed out. Empty fails G2 once decomposed."""
```

Append to `Task` (after `owning_team: str | None = None` and its docstring):

```python
    task_type: str = "code"
    """What kind of work this is: code, config, schema, docs."""
    patch_path: str | None = None
    """Pre-authored change the downstream lane applies. Labelled, not hidden:
    until LLM access lands, patch content is prepared ahead of time and the
    provenance field says so."""
```

Add at module end:

```python
@dataclass(frozen=True)
class Verdict:
    """Gate 3's output: the independent check, recorded as an artifact.

    `checked_by` is an honesty label, not decoration. Until LLM access lands
    it reads "rule-based-verifier", and every surface shows it. No phase
    approves its own work — including this one.
    """

    epic_id: str
    passed: bool
    findings: tuple[str, ...]
    checked_by: str
    checked_at: datetime


@dataclass(frozen=True)
class CalibrationRecord:
    """Predicted vs. actual per stream for one completed epic."""

    epic_id: str
    predicted_days: dict[str, float]
    actual_days: dict[str, float]
    error_pct: float
    factors: dict[str, float]


@dataclass(frozen=True)
class SkillAmendment:
    """One versioned change to a skill file, traceable to what triggered it."""

    skill: str
    version: int
    reason_code: str
    text: str
    triggered_by: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class DownstreamResult:
    """One downstream stage outcome for one task, with its real output."""

    task_id: str
    stage: str
    ok: bool
    detail: str
    output: str
    provenance: Provenance
```

- [ ] **Step 4: Run the full suite to verify green**

Run: `python -m pytest -q`
Expected: all tests PASS (existing 60 + new).

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/models.py tests/test_models.py
git commit -m "feat: contract additions — story quality fields, Verdict, calibration, amendment, downstream types

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Staged stories carry the quality fields; payload exposes them

**Files:**
- Modify: `s7_delivery/staged.py`
- Modify: `s7_delivery/pipeline.py` (function `_story_payload`)
- Test: `tests/test_gates.py` (created here with a placeholder-free first test; G2 tests in Task 7 extend it)

**Interfaces:**
- Consumes: Task 5's new `UserStory` fields.
- Produces: every story returned by `staged.stories()` has non-empty `purpose`, `impacts`, `feature_flag`, `rollback_plan`; `_story_payload` includes keys `"purpose"`, `"impacts"`, `"feature_flag"`, `"rollback_plan"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gates.py
"""Gates G0 and G2, and the staged data they must pass."""

from s7_delivery import pipeline, staged


def test_staged_stories_meet_the_quality_standard():
    for story in staged.stories():
        assert story.purpose, story.id
        assert story.impacts, story.id
        assert story.feature_flag, story.id
        assert story.rollback_plan, story.id


def test_story_payload_exposes_quality_fields():
    story = staged.stories()[0]
    payload = pipeline._story_payload(story)
    assert payload["purpose"] == story.purpose
    assert payload["impacts"] == list(story.impacts)
    assert payload["feature_flag"] == story.feature_flag
    assert payload["rollback_plan"] == story.rollback_plan
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gates.py -v`
Expected: FAIL — staged stories have empty defaults.

- [ ] **Step 3: Implement**

In `s7_delivery/staged.py`, read the existing `stories()` construction and add the four fields to each of the staged stories for EPIC-S7-001, in MapleSure vocabulary and consistent with each story's narrative. Concrete values to use:

- Sponsor identification story: `purpose="Let a plan sponsor start a disability claim from the portal instead of paper intake."`, `impacts=("sponsor portal UI", "member lookup API")`, `feature_flag="disability_online_submission"`, `rollback_plan="Disable the feature flag; the paper/PDF intake channel remains live and unchanged."`
- Claim details story: `purpose="Collect disability claim details online with pre-populated member data to cut re-keying errors."`, `impacts=("claim intake service", "member data API", "claims database")`, `feature_flag="disability_online_submission"`, `rollback_plan="Disable the feature flag; submissions in flight fall back to document upload intake."`
- Documents/status story: `purpose="Give sponsors upload and status visibility so intake stops being a black hole."`, `impacts=("document intake pipeline", "status API", "sponsor portal UI")`, `feature_flag="disability_online_submission"`, `rollback_plan="Disable the feature flag; documents revert to the existing indexing queue."`

(Match these to however many stories `staged.stories()` actually returns — one block per story, adjusted to its subject. Provenance stays `STAGED`; these are staged artifacts and remain labelled.)

In `s7_delivery/pipeline.py`, add to the dict returned by `_story_payload`:

```python
        "purpose": story.purpose,
        "impacts": list(story.impacts),
        "feature_flag": story.feature_flag,
        "rollback_plan": story.rollback_plan,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gates.py -q && python -m pytest -q`
Expected: all PASS (payload change is additive; the frozen console contract gains keys, loses none).

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/staged.py s7_delivery/pipeline.py tests/test_gates.py
git commit -m "feat: staged stories meet the story-quality standard; payload exposes the fields

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Gates G0 and G2

**Files:**
- Create: `s7_delivery/gates.py`
- Test: `tests/test_gates.py` (append)

**Interfaces:**
- Consumes: `pipeline.EpicDocument`, `models.UserStory`, Task 6's staged data.
- Produces: `GateFailure(gate: str, reason_code: str, detail: str)` (frozen dataclass), `gate0_intake(document: EpicDocument) -> tuple[GateFailure, ...]`, `gate2_story_quality(stories: tuple[UserStory, ...]) -> tuple[GateFailure, ...]`. Empty tuple = pass. `reason_code` values are load-bearing — the healing loop (Plan 3) keys on them: `no_sections`, `no_open_questions`, `missing_purpose`, `empty_acceptance`, `missing_impacts`, `missing_feature_flag`, `missing_rollback_plan`, `unsatisfied_acceptance`, `dangling_dependency`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_gates.py`)

```python
import dataclasses

from s7_delivery import gates
from s7_delivery.pipeline import load_epic


def test_gate0_passes_on_the_committed_epic():
    assert gates.gate0_intake(load_epic()) == ()


def test_gate0_fails_when_sections_missing(tmp_path):
    epic = tmp_path / "EPIC-X.md"
    epic.write_text("# EPIC-X — Bare epic with no numbered sections\n", encoding="utf-8")
    failures = gates.gate0_intake(load_epic(epic))
    codes = {f.reason_code for f in failures}
    assert "no_sections" in codes
    assert "no_open_questions" in codes
    assert all(f.gate == "G0" for f in failures)


def test_gate2_passes_on_staged_stories():
    assert gates.gate2_story_quality(staged.stories()) == ()


def test_gate2_names_each_missing_quality_field():
    story = staged.stories()[0]
    degraded = dataclasses.replace(
        story, purpose="", impacts=(), feature_flag="", rollback_plan=""
    )
    codes = [f.reason_code for f in gates.gate2_story_quality((degraded,))]
    assert codes.count("missing_purpose") == 1
    assert codes.count("missing_impacts") == 1
    assert codes.count("missing_feature_flag") == 1
    assert codes.count("missing_rollback_plan") == 1


def test_gate2_reports_unclaimed_acceptance_criteria():
    story = staged.stories()[0]
    degraded = dataclasses.replace(story, tasks=())  # nothing claims the ACs
    # An undecomposed story is a real state, not a G2 failure — G2 checks
    # quality fields only when tasks exist to claim ACs.
    codes = [f.reason_code for f in gates.gate2_story_quality((degraded,))]
    assert "unsatisfied_acceptance" not in codes

    if story.tasks:
        first_task = story.tasks[0]
        neutered = dataclasses.replace(first_task, satisfies=())
        retasked = dataclasses.replace(story, tasks=(neutered,) + story.tasks[1:])
        codes = [f.reason_code for f in gates.gate2_story_quality((retasked,))]
        assert "unsatisfied_acceptance" in codes


def test_gate2_reports_dangling_dependencies():
    story = staged.stories()[0]
    if not story.tasks:
        return  # nothing to check on an undecomposed story
    first = story.tasks[0]
    broken = dataclasses.replace(first, depends_on=("T-DOES-NOT-EXIST",))
    retasked = dataclasses.replace(story, tasks=(broken,) + story.tasks[1:])
    failures = gates.gate2_story_quality((retasked,))
    assert any(
        f.reason_code == "dangling_dependency" and "T-DOES-NOT-EXIST" in f.detail
        for f in failures
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gates.py -v`
Expected: new tests FAIL with `ModuleNotFoundError: No module named 's7_delivery.gates'`.

- [ ] **Step 3: Write the implementation**

```python
# s7_delivery/gates.py
"""Machine-checkable gates G0 and G2.

Gates return named failures rather than raising: a gate's job is to say
*exactly what is wrong* so a human can fix it — and so the healing loop can
key on `reason_code` and amend the responsible skill. An empty tuple is a
pass. Enforcement (refusing to run the next stage) lives in the workflow
layer, so no surface can route around it.

G0 checks the epic parsed into reviewable shape. G2 checks the story-quality
standard: purpose, testable acceptance criteria, impacts, feature flag,
rollback plan, every acceptance criterion claimed by a task, no dangling
dependencies. An undecomposed story (no tasks yet) is a real state, not a
failure — AC coverage is only checked once tasks exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from s7_delivery.models import UserStory
from s7_delivery.pipeline import EpicDocument


@dataclass(frozen=True)
class GateFailure:
    gate: str
    reason_code: str
    detail: str


def gate0_intake(document: EpicDocument) -> tuple[GateFailure, ...]:
    failures: list[GateFailure] = []
    if not document.sections:
        failures.append(
            GateFailure("G0", "no_sections", f"Epic {document.epic.id} has no numbered sections")
        )
    if not document.open_questions:
        failures.append(
            GateFailure(
                "G0",
                "no_open_questions",
                f"Epic {document.epic.id} lists no open questions — an epic with "
                "nothing unvalidated is more likely unexamined than complete",
            )
        )
    if not document.summary.strip():
        failures.append(
            GateFailure("G0", "no_summary", f"Epic {document.epic.id} has no summary")
        )
    return tuple(failures)


def gate2_story_quality(stories: tuple[UserStory, ...]) -> tuple[GateFailure, ...]:
    failures: list[GateFailure] = []
    for story in stories:
        def fail(code: str, detail: str) -> None:
            failures.append(GateFailure("G2", code, f"{story.id}: {detail}"))

        if not story.purpose.strip():
            fail("missing_purpose", "no purpose stated")
        if not story.acceptance:
            fail("empty_acceptance", "no acceptance criteria")
        if not story.impacts:
            fail("missing_impacts", "impacted components not listed")
        if not story.feature_flag.strip():
            fail("missing_feature_flag", "no feature flag named")
        if not story.rollback_plan.strip():
            fail("missing_rollback_plan", "no rollback plan stated")

        if story.tasks:
            for ac_id in story.unsatisfied():
                fail("unsatisfied_acceptance", f"criterion {ac_id} claimed by no task")
            known = {t.id for t in story.tasks}
            for task in story.tasks:
                for dep in task.depends_on:
                    if dep not in known:
                        fail(
                            "dangling_dependency",
                            f"task {task.id} depends on {dep}, which no task in this story defines",
                        )
    return tuple(failures)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gates.py -v && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/gates.py tests/test_gates.py
git commit -m "feat: gates G0 and G2 with named, healing-consumable failure codes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: G3 — the independent verifier

**Files:**
- Create: `s7_delivery/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `gates.gate2_story_quality` (Task 7), `models.Verdict` (Task 5), `artifacts.write_artifact` / `derived_ref` (Task 3), `pipeline.EpicDocument`, `models.Assessment`, `models.UserStory`.
- Produces: `verify_stories(document: EpicDocument, assessment: Assessment, stories: tuple[UserStory, ...]) -> Verdict`, `write_verdict(root: Path, verdict: Verdict, *, derived_from: tuple[str, ...] = ()) -> Path` (writes stage `"verify"`, artifact id `"verdict"`, producer `CHECKED_BY`). Module constants: `CHECKED_BY = "rule-based-verifier"` (the honesty label every surface shows) and `PROVENANCE = "live_rule_based"` — deliberately a plain plane-level string, not a `Provenance` enum value, because none of the enum's members honestly describes a deterministic check that ran live; the enum labels displayed pipeline artifacts, and verdicts are plane metadata.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_verifier.py
"""G3: the independent verifier. No phase approves its own work."""

import dataclasses

from s7_delivery import artifacts, staged, verifier
from s7_delivery.pipeline import load_epic


def test_verifier_passes_the_staged_pipeline_state():
    verdict = verifier.verify_stories(load_epic(), staged.assessment(), staged.stories())
    assert verdict.passed
    assert verdict.findings == ()
    assert verdict.checked_by == "rule-based-verifier"


def test_verifier_catches_story_pointing_at_wrong_epic():
    stories = staged.stories()
    wrong = dataclasses.replace(stories[0], epic_id="EPIC-OTHER")
    verdict = verifier.verify_stories(
        load_epic(), staged.assessment(), (wrong,) + stories[1:]
    )
    assert not verdict.passed
    assert any("EPIC-OTHER" in f for f in verdict.findings)


def test_verifier_catches_duplicate_acceptance_ids_across_stories():
    stories = staged.stories()
    if len(stories) < 2:
        return
    clash = dataclasses.replace(stories[1], acceptance=stories[0].acceptance)
    verdict = verifier.verify_stories(
        load_epic(), staged.assessment(), (stories[0], clash) + stories[2:]
    )
    assert not verdict.passed
    assert any("duplicate" in f.lower() for f in verdict.findings)


def test_verifier_folds_in_gate2_failures():
    stories = staged.stories()
    degraded = dataclasses.replace(stories[0], rollback_plan="")
    verdict = verifier.verify_stories(
        load_epic(), staged.assessment(), (degraded,) + stories[1:]
    )
    assert not verdict.passed
    assert any("missing_rollback_plan" in f for f in verdict.findings)


def test_write_verdict_lands_on_the_plane(tmp_path):
    verdict = verifier.verify_stories(load_epic(), staged.assessment(), staged.stories())
    path = verifier.write_verdict(tmp_path, verdict)
    envelope = artifacts.read_artifact(path)
    assert envelope["meta"]["stage"] == "verify"
    assert envelope["meta"]["producer"] == "rule-based-verifier"
    assert envelope["body"]["passed"] is True
    assert envelope["body"]["checked_by"] == "rule-based-verifier"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 's7_delivery.verifier'`.

- [ ] **Step 3: Write the implementation**

```python
# s7_delivery/verifier.py
"""Gate 3: independent verification of the story breakdown.

The structural rule this module encodes: **no phase approves its own work.**
The verifier is a separate module with its own output artifact, so a
downstream stage can refuse to run on unverified input rather than trusting
that someone looked.

Honesty label, stated once and shown everywhere: this verifier is
**rule-based**. There is no second model behind it until LLM access lands
(§ LLM access, CLAUDE.md), and no surface may present it as AI. When a
second model arrives, it drops in behind `verify_stories` and nothing else
changes — that seam is the point of the module boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from s7_delivery import artifacts, gates
from s7_delivery.models import Assessment, UserStory, Verdict
from s7_delivery.pipeline import EpicDocument

CHECKED_BY = "rule-based-verifier"
PROVENANCE = "live_rule_based"
"""Plane-level provenance string for verdicts. Deliberately not a
`Provenance` enum value: the enum labels displayed pipeline artifacts, and
none of its members honestly describes a deterministic check that ran live."""


def verify_stories(
    document: EpicDocument,
    assessment: Assessment,
    stories: tuple[UserStory, ...],
) -> Verdict:
    findings: list[str] = []

    for story in stories:
        if story.epic_id and story.epic_id != document.epic.id:
            findings.append(
                f"{story.id} points at {story.epic_id}, but this run is {document.epic.id}"
            )

    seen: dict[str, str] = {}
    for story in stories:
        for criterion in story.acceptance:
            if criterion.id in seen and seen[criterion.id] != story.id:
                findings.append(
                    f"duplicate acceptance id {criterion.id} in {seen[criterion.id]} and {story.id}"
                )
            seen[criterion.id] = story.id

    story_streams = {stream for story in stories for stream in story.streams}
    for task in assessment.tasks:
        if task.stream not in story_streams:
            findings.append(
                f"assessment routes work to {task.stream.value} but no story covers that stream"
            )

    for failure in gates.gate2_story_quality(stories):
        findings.append(f"{failure.reason_code}: {failure.detail}")

    return Verdict(
        epic_id=document.epic.id,
        passed=not findings,
        findings=tuple(findings),
        checked_by=CHECKED_BY,
        checked_at=datetime.now(UTC),
    )


def write_verdict(
    root: Path, verdict: Verdict, *, derived_from: tuple[str, ...] = ()
) -> Path:
    return artifacts.write_artifact(
        root,
        epic_id=verdict.epic_id,
        stage="verify",
        artifact_id="verdict",
        body={
            "epic_id": verdict.epic_id,
            "passed": verdict.passed,
            "findings": list(verdict.findings),
            "checked_by": verdict.checked_by,
            "checked_at": verdict.checked_at.isoformat(),
        },
        producer=CHECKED_BY,
        provenance=PROVENANCE,
        derived_from=derived_from,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_verifier.py -v && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add s7_delivery/verifier.py tests/test_verifier.py
git commit -m "feat: G3 independent verifier with verdict artifacts, labelled rule-based

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Gitignore the plane; full-suite check; feature-status flip

**Files:**
- Modify: `.gitignore`
- Modify: `docs/s7-feature-priorities.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a clean tree where `artifacts/` can never be committed by accident, and an honest status file.

- [ ] **Step 1: Add `artifacts/` to `.gitignore`**

Append (with the comment, matching the file's existing style):

```
# Runtime artifact plane — regenerated by running the pipeline; never committed
artifacts/
```

- [ ] **Step 2: Verify ignore works**

Run: `mkdir -p artifacts/EPIC-TEST && touch artifacts/EPIC-TEST/x.json && git status --porcelain | grep artifacts; rm -rf artifacts`
Expected: grep prints nothing (exit 1 from grep is the pass signal).

- [ ] **Step 3: Update `docs/s7-feature-priorities.md` statuses**

In the sections for **4 · Provenance Ledger**, **10 · Staleness Detection**, **3 · Story Quality Standards**, **9 · Gates 0–2**, and **6 · Independent Review**, change the `**Status:**` line to reflect what now runs, e.g. for the ledger: `**Status:** built (Plan 1) — hash-chained \`artifacts/ledger.jsonl\`, envelopes with \`derived_from\`, staleness detection. Tamper test in \`tests/test_ledger.py\`.` Word each one to describe only what this plan actually shipped: G3 is "rule-based verifier built and labelled; second-model review still pending LLM access"; five-gate *enforcement wiring* and G1/G4 remain with Plans 2+.

- [ ] **Step 4: Run the full suite one last time**

Run: `python -m pytest -q`
Expected: everything PASS.

- [ ] **Step 5: Commit**

```bash
git add .gitignore docs/s7-feature-priorities.md
git commit -m "chore: gitignore the artifact plane; flip feature statuses for plan 1

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## What this plan deliberately leaves for Plans 2–4

- **Plan 2:** `target_app/maplesure_portal/`, the downstream lane (build → test → docs → release), Gate 4, gate *enforcement wiring* in the workflow layer, `DownstreamResult` consumers.
- **Plan 3:** `calibration.py`, EPIC-S7-002/003 with actuals, `healing.py`, `s7_delivery/skills/` + `rules/` files, telemetry-to-plane session records.
- **Plan 4:** CLI runner `python -m s7_delivery.run`, console panels (ledger/traceability, KPIs, factory), deliverables v2 (deck, teleprompt, HTML).
