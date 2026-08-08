"""LLM call telemetry and cost summaries."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Fill this with approved rates before treating cost as financial reporting.
MODEL_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {}


def _telemetry_path() -> Path:
    return Path(os.environ.get("LLM_TELEMETRY_PATH", ".cache/llm/telemetry.jsonl"))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def log_call(
    *,
    scenario: str,
    beat: str,
    provider: str,
    model: str,
    cached: bool,
    latency_s: float,
    input_tokens: int | None,
    output_tokens: int | None,
    success: bool,
    error: str | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> None:
    """Append one provider-neutral telemetry row for an LLM call.

    `cache_read_tokens` and `cache_write_tokens` follow the same discipline as
    cost: **log what the provider actually reports, and leave it unset when the
    provider reports nothing.** They stay `None` rather than becoming `0`,
    because zero is a measurement and `None` is an admission. A provider with no
    cache counters must not be made to look like one with a perfect miss rate.
    """
    path = _telemetry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "scenario": scenario,
        "beat": beat,
        "provider": provider,
        "model": model,
        "cached": cached,
        "latency_s": round(latency_s, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "success": success,
        "error": error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def read_calls(path: Path | None = None) -> list[dict[str, Any]]:
    """Read telemetry JSONL rows from disk."""
    target = path or _telemetry_path()
    if not target.exists():
        return []

    calls: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            calls.append(json.loads(line))
    return calls


def scenario_of(cache_key: str | None) -> tuple[str, str]:
    """Split a cache key into a coarse scenario and beat for dashboards."""
    if not cache_key:
        return "unknown", "unknown"

    prefix = cache_key.split(":", 1)[0]
    parts = prefix.split("_", 1)
    if len(parts) != 2:
        return "unknown", prefix
    return parts[0], parts[1]


def estimated_cost_usd(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Return estimated USD cost when approved model rates are configured."""
    rates = MODEL_PRICING_USD_PER_1M.get(model)
    if rates is None or input_tokens is None or output_tokens is None:
        return None

    input_rate, output_rate = rates
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


def _sum_or_none(rows: list[dict[str, Any]], field: str) -> int | None:
    """Total a token field, or `None` when no row reported it.

    Distinguishes "every provider reported zero" from "no provider reported".
    A plain `sum(... or 0)` collapses the two and turns silence into a number.
    """
    values = [row.get(field) for row in rows]
    known = [int(v) for v in values if isinstance(v, int)]
    return sum(known) if known else None


@dataclass(frozen=True)
class ScenarioSummary:
    scenario: str
    total_calls: int
    live_calls: int
    cached_calls: int
    input_tokens: int
    output_tokens: int
    avg_live_latency_s: float | None
    avg_cached_latency_s: float | None
    estimated_cost_usd: float | None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


def summarize_by_scenario(calls: list[dict[str, Any]]) -> list[ScenarioSummary]:
    """Aggregate telemetry rows by scenario."""
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_scenario.setdefault(str(call.get("scenario", "unknown")), []).append(call)

    summaries: list[ScenarioSummary] = []
    for scenario, rows in sorted(by_scenario.items()):
        live = [row for row in rows if not row.get("cached")]
        cached = [row for row in rows if row.get("cached")]
        input_tokens = sum(int(row.get("input_tokens") or 0) for row in live)
        output_tokens = sum(int(row.get("output_tokens") or 0) for row in live)
        costs = [
            estimated_cost_usd(
                str(row.get("model", "")),
                row.get("input_tokens"),
                row.get("output_tokens"),
            )
            for row in live
        ]
        known_costs = [cost for cost in costs if cost is not None]
        summaries.append(
            ScenarioSummary(
                scenario=scenario,
                total_calls=len(rows),
                live_calls=len(live),
                cached_calls=len(cached),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                avg_live_latency_s=(
                    sum(float(row["latency_s"]) for row in live) / len(live) if live else None
                ),
                avg_cached_latency_s=(
                    sum(float(row["latency_s"]) for row in cached) / len(cached) if cached else None
                ),
                estimated_cost_usd=sum(known_costs) if known_costs else None,
                cache_read_tokens=_sum_or_none(rows, "cache_read_tokens"),
                cache_write_tokens=_sum_or_none(rows, "cache_write_tokens"),
            )
        )
    return summaries


def cache_hit_rate(calls: list[dict[str, Any]]) -> float | None:
    """Return the fraction of telemetry rows served from cache or replay."""
    if not calls:
        return None
    return sum(1 for call in calls if call.get("cached")) / len(calls)


def cache_efficiency(calls: list[dict[str, Any]]) -> float | None:
    """Return the cache-read-to-write token ratio, or `None` if unmeasured.

    The ratio is the headline number for prompt-cache economics: a cache read
    costs roughly a tenth of a fresh input token and about an eighth of a cache
    write, so reusing a prefix many times is where the saving lives. A pipeline
    that writes a prefix and reads it once has gained nothing.

    Returns `None` — never `0.0` — when no provider reported cache counters, and
    `None` when writes are zero, because a ratio over zero writes is undefined
    rather than infinite. Both cases must render as "not measured" in any view;
    see CLAUDE.md § Cache-efficient agent architecture, decisions 3 and 4.
    """
    reads = _sum_or_none(calls, "cache_read_tokens")
    writes = _sum_or_none(calls, "cache_write_tokens")
    if reads is None or not writes:
        return None
    return reads / writes
