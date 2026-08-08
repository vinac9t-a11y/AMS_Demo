"""The prompt-prefix convention, and the economics that depend on it.

These guard CLAUDE.md § Cache-efficient agent architecture. The mechanism they
protect is easy to break by accident and silent when broken: a prompt whose
stable text drifts to the wrong side of a volatile segment still *works*, it
just quietly stops earning cache reads. Only a test notices.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import common.llm as llm
from common.prompt import LAYER_ORDER, PromptLayers, stable_prefix_of
from common.telemetry import cache_efficiency, log_call, read_calls, summarize_by_scenario

# --- assembly order ---------------------------------------------------------


def test_layers_assemble_most_stable_first() -> None:
    """The whole mechanism is the order. If this flips, caching stops paying."""
    layers = PromptLayers(rules="RULES", role="ROLE", memory="MEM", ref="REF", task="TASK")
    system, prompt = layers.assemble()

    assert system == "RULES\n\nROLE"
    assert prompt == "MEM\n\nREF\n\nTASK"
    assert prompt.index("MEM") < prompt.index("REF") < prompt.index("TASK")


def test_absent_layers_leave_no_gap() -> None:
    """A missing layer must contribute nothing at all.

    If an absent layer left a blank separator, the assembled text — and so the
    cache key — would depend on which layers happened to be set, and two callers
    meaning the same thing would miss each other's recordings.
    """
    assert PromptLayers(task="T").assemble() == (None, "T")
    assert PromptLayers(task="T", rules="R").assemble() == ("R", "T")
    assert PromptLayers(task="T", memory="", ref="   ").assemble() == (None, "T")


def test_replace_task_holds_the_prefix_still() -> None:
    """The loop case: only the task changes, so the prefix stays cacheable."""
    first = PromptLayers(rules="RULES", role="ROLE", memory="MEM", ref="REF", task="one")
    second = first.replace_task("two")

    assert stable_prefix_of(first) == stable_prefix_of(second)
    assert first.system == second.system
    assert first.prompt != second.prompt


def test_layer_order_is_the_single_source_of_truth() -> None:
    """Assembly and the declared order cannot drift apart."""
    assert LAYER_ORDER == ("rules", "role", "memory", "ref", "task")
    assert set(LAYER_ORDER) == set(PromptLayers.__dataclass_fields__)


def test_separator_is_platform_independent() -> None:
    """A recording made on one OS must replay on another.

    `os.linesep` here would make every committed recording miss on Windows.
    """
    assert "\r" not in PromptLayers(task="a", rules="b").prompt
    assert "\r" not in str(PromptLayers(task="a", rules="b").system)


# --- the layers reach the provider through complete() -----------------------


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in ("LLM_MODE", "LLM_PROVIDER", "LLM_REPLAY_DIR", "LLM_CACHE_DIR",
                "LLM_TELEMETRY_PATH", "LLM_NO_CACHE", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    monkeypatch.setenv("LLM_MODE", "record")
    monkeypatch.setenv("LLM_REPLAY_DIR", str(tmp_path / "replay"))
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))


def _fake_provider(seen: dict[str, object], usage: llm.Usage):
    def caller(prompt: str, system: str | None, json_mode: bool):
        seen["prompt"] = prompt
        seen["system"] = system
        return "response", usage

    return caller


def test_complete_splits_layers_into_system_and_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS, "anthropic", _fake_provider(seen, llm.Usage())
    )

    llm.complete(PromptLayers(rules="RULES", role="ROLE", memory="MEM", task="TASK"))

    assert seen["system"] == "RULES\n\nROLE"
    assert seen["prompt"] == "MEM\n\nTASK"


def test_changing_only_the_task_changes_only_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the cache depends on, asserted at the provider boundary."""
    seen: dict[str, object] = {}
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS, "anthropic", _fake_provider(seen, llm.Usage())
    )
    base = PromptLayers(rules="RULES", role="ROLE", task="one")

    llm.complete(base)
    first_system = seen["system"]
    llm.complete(base.replace_task("two"))

    assert seen["system"] == first_system
    assert seen["prompt"] == "two"


def test_a_bare_string_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back-compat: a plain string is the task layer alone."""
    seen: dict[str, object] = {}
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS, "anthropic", _fake_provider(seen, llm.Usage())
    )

    llm.complete("just a task")

    assert seen["prompt"] == "just a task"
    assert seen["system"] is None


# --- cache counters: measured or unset, never invented ----------------------


def test_cache_counters_survive_a_replay_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recorded run must report the economics of the call actually made.

    Without this, cost per release silently collapses to "not measured" the
    moment the demo switches to replay — which is the mode the demo runs in.
    """
    usage = llm.Usage(
        input_tokens=100, output_tokens=20, cache_read_tokens=900, cache_write_tokens=80
    )
    monkeypatch.setitem(llm._PROVIDER_CALLERS, "anthropic", _fake_provider({}, usage))
    llm.complete(PromptLayers(rules="R", task="T"), cache_key="s7_assess")

    monkeypatch.setenv("LLM_MODE", "replay")
    recovered: dict[str, object] = {}
    llm.complete(PromptLayers(rules="R", task="T"), cache_key="s7_assess", usage_out=recovered)

    assert recovered["cache_read_tokens"] == 900
    assert recovered["cache_write_tokens"] == 80


def test_a_provider_without_cache_counters_reports_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset, not zero. Zero is a measurement; None is an admission."""
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS,
        "anthropic",
        _fake_provider({}, llm.Usage(input_tokens=10, output_tokens=2)),
    )
    llm.complete("task", cache_key="s7_assess")

    row = read_calls()[-1]
    assert row["input_tokens"] == 10
    assert row["cache_read_tokens"] is None
    assert row["cache_write_tokens"] is None


def test_cache_efficiency_is_none_when_unmeasured() -> None:
    """No counters must render as "not measured", never as a ratio of zero."""
    assert cache_efficiency([]) is None
    assert cache_efficiency([{"cache_read_tokens": None, "cache_write_tokens": None}]) is None
    # Reads with no writes is undefined, not infinite.
    assert cache_efficiency([{"cache_read_tokens": 500, "cache_write_tokens": 0}]) is None


def test_cache_efficiency_ratio() -> None:
    calls = [
        {"cache_read_tokens": 800, "cache_write_tokens": 50},
        {"cache_read_tokens": 200, "cache_write_tokens": 50},
    ]
    assert cache_efficiency(calls) == 10.0


def test_summary_distinguishes_unreported_from_zero() -> None:
    """`sum(x or 0)` would turn silence into a confident zero. It must not."""
    for _ in range(2):
        log_call(
            scenario="s7",
            beat="assess",
            provider="anthropic",
            model="m",
            cached=False,
            latency_s=0.1,
            input_tokens=10,
            output_tokens=2,
            success=True,
            cache_read_tokens=None,
        )

    summary = summarize_by_scenario(read_calls())[0]
    assert summary.input_tokens == 20
    assert summary.cache_read_tokens is None
