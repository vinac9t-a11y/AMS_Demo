"""Determinism guarantees for common.llm.

These are the tests that have to stay green for the demo to be safe to run:
a fresh clone with no API keys must reproduce every beat from the committed
recordings, and must fail loudly rather than quietly reaching the network.

Two of these guard specific traps recorded in CLAUDE.md that the sibling S3
build hit in production:

- `test_prompt_edit_invalidates_stable_cache_key` — a cache keyed on an explicit
  `cache_key` alone does not invalidate when the prompt changes, so editing a
  prompt appears to do nothing.
- `test_replay_ignores_llm_no_cache` — committed recordings are a deliverable,
  not a cache, and must not be switched off by a cache flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import common.llm as llm

_ENV_KEYS = (
    "LLM_MODE",
    "LLM_PROVIDER",
    "LLM_CACHE_DIR",
    "LLM_REPLAY_DIR",
    "LLM_NO_CACHE",
    "LLM_TELEMETRY_PATH",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pin every env var the module reads, so a developer's real .env cannot
    change the result of a test run."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    monkeypatch.setenv("LLM_REPLAY_DIR", str(tmp_path / "replay"))
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))


def _recording_path(
    prompt: str, *, system: str | None = None, cache_key: str | None = None
) -> Path:
    return llm._path_for_mode(
        mode="replay",
        provider="anthropic",
        model="test-model",
        system=system,
        prompt=prompt,
        cache_key=cache_key,
    )


def _write_recording(
    prompt: str, response: str, *, system: str | None = None, cache_key: str | None = None
) -> Path:
    path = _recording_path(prompt, system=system, cache_key=cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt": prompt,
                "system": system,
                "provider": "anthropic",
                "model": "test-model",
                "response": response,
            }
        ),
        encoding="utf-8",
    )
    return path


def _explode(*_args, **_kwargs):
    raise AssertionError("a live provider call was attempted")


# --- replay is the default, and it is offline ------------------------------


def test_default_mode_is_replay() -> None:
    assert llm._llm_mode() == "replay"


def test_replay_miss_raises_llm_error_naming_the_path() -> None:
    with pytest.raises(llm.LLMError) as excinfo:
        llm.complete("an unrecorded prompt")
    message = str(excinfo.value)
    assert str(_recording_path("an unrecorded prompt")) in message
    assert "record" in message.lower()


def test_replay_hit_returns_the_recorded_response() -> None:
    _write_recording("what is the epic?", "a recorded answer")
    assert llm.complete("what is the epic?") == "a recorded answer"


def test_replay_never_reaches_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replay miss must fail, not quietly go live on stage."""
    monkeypatch.setitem(llm._PROVIDER_CALLERS, "anthropic", _explode)
    with pytest.raises(llm.LLMError):
        llm.complete("unrecorded")


def test_replay_needs_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_recording("offline", "works with no key")
    assert llm.complete("offline") == "works with no key"


# --- the S3 cache-key trap -------------------------------------------------


def test_prompt_edit_invalidates_stable_cache_key() -> None:
    """Editing a prompt must miss the recording even when cache_key is fixed.

    The sibling build keyed solely on cache_key, so a changed prompt silently
    replayed the old response and the edit appeared to do nothing.
    """
    _write_recording("version one of the prompt", "stale", cache_key="assessment")
    with pytest.raises(llm.LLMError):
        llm.complete("version two of the prompt", cache_key="assessment")


def test_system_edit_invalidates_stable_cache_key() -> None:
    _write_recording("same prompt", "stale", system="system A", cache_key="assessment")
    with pytest.raises(llm.LLMError):
        llm.complete("same prompt", system="system B", cache_key="assessment")


def test_cache_key_still_distinguishes_identical_prompts() -> None:
    """cache_key must remain meaningful — it groups a call for telemetry."""
    assert _recording_path("p", cache_key="beat-a") != _recording_path("p", cache_key="beat-b")


# --- recordings are a deliverable, not a cache -----------------------------


def test_replay_ignores_llm_no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_NO_CACHE disables the ephemeral live-mode cache only.

    It must not disable committed replay recordings — otherwise setting it once
    turns every recorded beat into a hard failure.
    """
    _write_recording("recorded", "still replays")
    monkeypatch.setenv("LLM_NO_CACHE", "1")
    assert llm.complete("recorded") == "still replays"


def test_record_mode_refreshes_an_existing_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    """`record` means call live and refresh, not short-circuit on what is there."""
    path = _write_recording("prompt", "the old response")
    monkeypatch.setenv("LLM_MODE", "record")
    monkeypatch.setitem(
        llm._PROVIDER_CALLERS,
        "anthropic",
        lambda *_a, **_k: ("the new response", llm.Usage(input_tokens=10, output_tokens=5)),
    )
    assert llm.complete("prompt") == "the new response"
    assert json.loads(path.read_text(encoding="utf-8"))["response"] == "the new response"


def test_replay_and_cache_directories_are_separate() -> None:
    replay = llm._path_for_mode(
        mode="replay", provider="anthropic", model="m", system=None, prompt="p", cache_key=None
    )
    live = llm._path_for_mode(
        mode="live", provider="anthropic", model="m", system=None, prompt="p", cache_key=None
    )
    assert replay.parent != live.parent


# --- misconfiguration fails clearly ----------------------------------------


def test_unknown_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "reply")
    with pytest.raises(llm.LLMError):
        llm.complete("anything")


def test_malformed_recording_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    path = _recording_path("p")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(llm.LLMError):
        llm.complete("p")


# --- JSON parsing ----------------------------------------------------------


def test_parse_json_response_extracts_required_keys() -> None:
    parsed = llm.parse_json_response('{"tasks": [], "coverage": 0.6}', {"tasks", "coverage"})
    assert parsed["coverage"] == 0.6


def test_parse_json_response_rejects_missing_required_key() -> None:
    with pytest.raises(llm.LLMError):
        llm.parse_json_response('{"tasks": []}', {"tasks", "coverage"})
