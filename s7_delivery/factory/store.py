"""The artifact plane for factory runs.

One directory per run under `artifacts/runs/<run-id>/`, deterministic paths per
stage (spec §19). Two write disciplines, deliberately different:

- **Current-state JSON** (run.json, stories.json, …) is written atomically:
  tmp file in the same directory, then `os.replace`. A crash mid-write leaves
  the previous version intact, never a half-file.
- **Ledgers** (provenance.jsonl, activity.jsonl, approvals.jsonl,
  amendments.jsonl) are append-only. Nothing in this module can overwrite a
  ledger line; history is the product.

Run ids come from `next_run_id`, path segments are validated against a strict
pattern, and every path this module touches is resolved under the runs root —
a browser-supplied id can never escape it (spec §21).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_ROOT = REPO_ROOT / "artifacts" / "runs"

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StoreError(Exception):
    pass


def _safe(segment: str) -> str:
    if not _SAFE_SEGMENT.match(segment) or ".." in segment:
        raise StoreError(f"Unsafe path segment: {segment!r}")
    return segment


def sha256_of(payload: Any) -> str:
    """Content hash of a JSON-serialisable payload, key-order independent."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class RunStore:
    """All disk access for one run. The engine never touches paths directly."""

    def __init__(self, run_id: str, root: Path | None = None):
        self.run_id = _safe(run_id)
        self.root = (root or RUNS_ROOT) / self.run_id

    # --- paths -------------------------------------------------------------

    def path(self, *segments: str) -> Path:
        parts = [_safe(s) for s in segments]
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise StoreError(f"Path escapes run directory: {candidate}")
        return candidate

    def exists(self, *segments: str) -> bool:
        return self.path(*segments).exists()

    # --- current-state JSON (atomic) ---------------------------------------

    def write_json(self, payload: Any, *segments: str) -> Path:
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        target = self.path(*segments)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return target

    def read_json(self, *segments: str) -> Any:
        target = self.path(*segments)
        if not target.exists():
            raise StoreError(f"Missing artifact: {target.relative_to(self.root)}")
        return json.loads(target.read_text(encoding="utf-8"))

    def read_json_or(self, default: Any, *segments: str) -> Any:
        try:
            return self.read_json(*segments)
        except StoreError:
            return default

    def write_text(self, text: str, *segments: str) -> Path:
        target = self.path(*segments)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return target

    def read_text(self, *segments: str) -> str:
        target = self.path(*segments)
        if not target.exists():
            raise StoreError(f"Missing artifact: {target.relative_to(self.root)}")
        return target.read_text(encoding="utf-8")

    # --- ledgers (append-only) ---------------------------------------------

    def append(self, record: Any, ledger: str) -> None:
        if not ledger.endswith(".jsonl"):
            raise StoreError("Ledgers are .jsonl files")
        if isinstance(record, BaseModel):
            record = record.model_dump(mode="json")
        target = self.path(ledger)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_ledger(self, ledger: str) -> list[dict]:
        target = self.path(ledger)
        if not target.exists():
            return []
        out: list[dict] = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out


def list_runs(root: Path | None = None) -> list[str]:
    base = root or RUNS_ROOT
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def next_run_id(root: Path | None = None) -> str:
    existing = list_runs(root)
    numbers = [
        int(m.group(1))
        for name in existing
        if (m := re.match(r"^S7-(\d{5})$", name))
    ]
    return f"S7-{(max(numbers) + 1 if numbers else 1):05d}"
