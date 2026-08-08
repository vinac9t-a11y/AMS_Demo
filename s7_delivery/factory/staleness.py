"""Staleness detection over the provenance ledger (spec §15).

An artifact is **stale** when any of its inputs — transitively — has a newer
version recorded *after* the artifact's own latest version. The ledger is the
single source: every record carries `inputs` (upstream artifact ids) and the
ledger's append order gives "after" without trusting wall clocks.

No artifact is ever silently updated: correction produces a new version with
its own provenance record, which is what clears the stale flag — the detector
just re-reads the ledger.
"""

from __future__ import annotations

from typing import Any


def detect(provenance: list[dict]) -> list[dict[str, Any]]:
    """Return StalenessResult dicts for every currently-stale artifact."""
    if not provenance:
        return []

    # Latest record (and its ledger position) per artifact.
    latest: dict[str, tuple[int, dict]] = {}
    for idx, rec in enumerate(provenance):
        latest[rec["artifact_id"]] = (idx, rec)

    def newest_upstream(artifact_id: str, seen: frozenset[str]) -> tuple[int, str] | None:
        """Ledger position of the newest transitive input record, with the
        input's id — or None when the artifact has no known inputs."""
        if artifact_id in seen or artifact_id not in latest:
            return None
        _idx, rec = latest[artifact_id]
        best: tuple[int, str] | None = None
        for input_id in rec.get("inputs", []):
            if input_id not in latest:
                continue  # references something outside the ledger (e.g. a task id)
            input_idx, _ = latest[input_id]
            candidate = (input_idx, input_id)
            deeper = newest_upstream(input_id, seen | {artifact_id})
            if deeper and deeper[0] > candidate[0]:
                candidate = deeper
            if best is None or candidate[0] > best[0]:
                best = candidate
        return best

    results: list[dict[str, Any]] = []
    for artifact_id, (idx, rec) in latest.items():
        upstream = newest_upstream(artifact_id, frozenset())
        if upstream is None:
            continue
        upstream_idx, upstream_id = upstream
        if upstream_idx > idx:
            _u_idx, u_rec = latest[upstream_id]
            results.append({
                "artifact_id": artifact_id,
                "artifact_type": rec["artifact_type"],
                "version": rec["version"],
                "status": "stale",
                "reason": (
                    f"Upstream {upstream_id} changed to v{u_rec['version']} "
                    f"({u_rec['action']}) after this artifact was produced"
                ),
            })
    results.sort(key=lambda r: r["artifact_id"])
    return results
