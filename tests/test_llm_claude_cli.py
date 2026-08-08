"""The claude_cli provider — record-time shell-out to the headless claude CLI.

All subprocess calls are faked; no test here touches the real CLI. The one
genuine invocation happens once, by hand, at record time (see the plan's
Task 1 Step 5 smoke test).
"""

import json
import subprocess

import pytest

import common.llm as llm


def _fake_run(payload):
    def fake(cmd, **kwargs):
        fake.cmd = cmd
        fake.stdin = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    return fake


def test_claude_cli_parses_result_and_usage(monkeypatch):
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "hello from the model",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
        },
    }
    fake = _fake_run(payload)
    monkeypatch.setattr(subprocess, "run", fake)
    text, usage = llm._call_claude_cli("say hello", None, False)
    assert text == "hello from the model"
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.cache_read_tokens == 3
    assert usage.cache_write_tokens == 2
    assert fake.cmd[0] == "claude"
    assert "-p" in fake.cmd


def test_claude_cli_missing_usage_stays_none(monkeypatch):
    payload = {"is_error": False, "result": "ok"}
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    _, usage = llm._call_claude_cli("x", None, False)
    assert usage.input_tokens is None
    assert usage.cache_read_tokens is None


def test_claude_cli_json_mode_appends_instruction(monkeypatch):
    payload = {"is_error": False, "result": "{}", "usage": {}}
    fake = _fake_run(payload)
    monkeypatch.setattr(subprocess, "run", fake)
    llm._call_claude_cli("give me json", "sys prompt", True)
    assert "JSON only" in fake.stdin
    assert "--append-system-prompt" in fake.cmd
    assert "sys prompt" in fake.cmd


def test_claude_cli_error_result_raises(monkeypatch):
    payload = {"is_error": True, "result": "boom"}
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    with pytest.raises(llm.LLMError, match="boom"):
        llm._call_claude_cli("x", None, False)


def test_claude_cli_nonzero_exit_raises(monkeypatch):
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(llm.LLMError, match="not logged in"):
        llm._call_claude_cli("x", None, False)


def test_claude_cli_registered():
    assert "claude_cli" in llm._PROVIDER_CALLERS
    assert "claude_cli" in llm._PROVIDER_STREAMERS
    assert "claude_cli" in llm._PROVIDER_NAMES


def test_claude_cli_model_env_override(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI_MODEL", "opus")
    assert llm._model_for("claude_cli") == "opus"
    payload = {"is_error": False, "result": "ok"}
    fake = _fake_run(payload)
    monkeypatch.setattr(subprocess, "run", fake)
    llm._call_claude_cli("x", None, False)
    assert "--model" in fake.cmd
    assert "opus" in fake.cmd
