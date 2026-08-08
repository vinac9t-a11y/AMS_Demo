"""Provider-agnostic LLM access.

Every LLM call in this repo goes through this module. Callers pass prompt text
and receive response text; provider SDK objects and response shapes stay here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.prompt import PromptLayers
from common.telemetry import log_call, scenario_of

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

_PROVIDER_NAMES = "'openai', 'anthropic', 'bedrock', 'ollama', 'custom', or 'claude_cli'"
_JSON_INSTRUCTION = "\n\nRespond with valid JSON only, no surrounding prose."


class LLMError(Exception):
    """Raised for provider failures, replay misses, or LLM misconfiguration."""


@dataclass(frozen=True)
class Usage:
    """Token counts for one provider call, provider-neutral.

    Every field is optional and defaults to `None`, which means *this provider
    did not report it* — not zero. The distinction is load-bearing: cache
    counters are only available from providers that implement prompt caching,
    and a zero would present a provider that cannot measure as one that measured
    a total miss. See CLAUDE.md § Cache-efficient agent architecture, decision 3.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


def _int_or_none(value: Any) -> int | None:
    """Coerce a provider usage field, preserving 'absent' as `None`."""
    return value if isinstance(value, int) else None


def _anthropic_usage(raw: Any) -> Usage:
    """Read an Anthropic-shaped usage object, including its cache counters.

    Anthropic reports `cache_creation_input_tokens` (a write — the first call
    that populates a prefix) and `cache_read_input_tokens` (a read — every
    subsequent call that reuses it). Older SDK responses omit both; `getattr`
    with a `None` default keeps those unset rather than inventing zeros.
    """
    return Usage(
        input_tokens=_int_or_none(getattr(raw, "input_tokens", None)),
        output_tokens=_int_or_none(getattr(raw, "output_tokens", None)),
        cache_read_tokens=_int_or_none(getattr(raw, "cache_read_input_tokens", None)),
        cache_write_tokens=_int_or_none(getattr(raw, "cache_creation_input_tokens", None)),
    )


def _openai_usage(raw: Any) -> Usage:
    """Read an OpenAI-compatible usage object.

    No cache counters: the OpenAI-compatible surface does not report them, and
    this covers the `custom` and `ollama` providers too. They stay `None`, which
    is what makes a ratio built from them read as "not measured".
    """
    if raw is None:
        return Usage()
    return Usage(
        input_tokens=_int_or_none(getattr(raw, "prompt_tokens", None)),
        output_tokens=_int_or_none(getattr(raw, "completion_tokens", None)),
    )


def _cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))


def _replay_dir() -> Path:
    return Path(os.environ.get("LLM_REPLAY_DIR", "s7_delivery/cache/llm"))


def _cache_enabled() -> bool:
    return os.environ.get("LLM_NO_CACHE", "0") != "1"


def _llm_mode() -> str:
    mode = os.environ.get("LLM_MODE", "replay").lower()
    if mode not in {"live", "record", "replay"}:
        raise LLMError(f"Unknown LLM_MODE {mode!r}; expected 'live', 'record', or 'replay'")
    return mode


def _resolve_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider not in _PROVIDER_CALLERS:
        raise LLMError(f"Unknown LLM_PROVIDER {provider!r}; expected {_PROVIDER_NAMES}")
    return provider


def _model_for(provider: str) -> str:
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    if provider == "bedrock":
        return os.environ.get("BEDROCK_MODEL", "anthropic.claude-sonnet-5")
    if provider == "ollama":
        return os.environ.get("OLLAMA_MODEL", "llama3.1")
    if provider == "custom":
        return os.environ.get("CUSTOM_LLM_MODEL", "custom")
    if provider == "claude_cli":
        return os.environ.get("CLAUDE_CLI_MODEL", "claude-cli")
    return os.environ.get("OPENAI_MODEL", "gpt-5")


def _cache_path(
    *,
    directory: Path,
    provider: str,
    model: str,
    system: str | None,
    prompt: str,
    cache_key: str | None,
) -> Path:
    # Deliberate S7 correction: cache_key labels/groups a call, but prompt and
    # system text always enter the digest so prompt edits cannot hit stale replay.
    key_material = json.dumps(
        [cache_key or "", provider, model, system or "", prompt],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return directory / f"{digest}.json"


def _path_for_mode(
    *,
    mode: str,
    provider: str,
    model: str,
    system: str | None,
    prompt: str,
    cache_key: str | None,
) -> Path:
    directory = _replay_dir() if mode in {"replay", "record"} else _cache_dir()
    return _cache_path(
        directory=directory,
        provider=provider,
        model=model,
        system=system,
        prompt=prompt,
        cache_key=cache_key,
    )


def _read_entry(path: Path, *, obey_cache_toggle: bool) -> dict[str, Any] | None:
    if (obey_cache_toggle and not _cache_enabled()) or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM cache entry {path} is malformed") from exc
    if not isinstance(data, dict) or "response" not in data:
        raise LLMError(f"LLM cache entry {path} is missing a response")
    return data


def _write_entry(
    path: Path,
    *,
    prompt: str,
    system: str | None,
    provider: str,
    model: str,
    response: str,
    usage: Usage | None = None,
    obey_cache_toggle: bool,
) -> None:
    if obey_cache_toggle and not _cache_enabled():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "prompt": prompt,
        "system": system,
        "provider": provider,
        "model": model,
        "response": response,
    }
    # Persist the whole Usage, cache counters included, so a replayed run
    # reports the economics of the call that was actually made rather than
    # silently dropping to "not measured" the moment it comes off disk.
    if usage is not None:
        payload["usage"] = usage.as_dict()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _missing_replay_error(path: Path) -> LLMError:
    return LLMError(
        f"Missing LLM replay recording at {path}. Set LLM_MODE=record to make a "
        "live provider call and write this committed recording."
    )


def _usage_from_entry(
    entry: dict[str, Any],
    *,
    response: str,
    usage_out: dict[str, Any] | None,
) -> Usage:
    """Recover the recorded `Usage` from a cache or replay entry.

    A recording written before cache counters existed simply has no key for
    them, so they come back `None` — an old recording reports "not measured"
    rather than a fabricated zero, and does not need re-rolling to stay honest.

    When an entry carries no usage at all, `usage_out` receives a rough
    character-based estimate flagged `estimated: True` for callers that want a
    rough size, but the returned `Usage` stays empty. Estimates are never
    allowed to reach telemetry, because telemetry feeds the cost number.
    """
    usage = entry.get("usage")
    if isinstance(usage, dict):
        recovered = Usage(
            input_tokens=_int_or_none(usage.get("input_tokens")),
            output_tokens=_int_or_none(usage.get("output_tokens")),
            cache_read_tokens=_int_or_none(usage.get("cache_read_tokens")),
            cache_write_tokens=_int_or_none(usage.get("cache_write_tokens")),
        )
        if usage_out is not None:
            usage_out.update(recovered.as_dict())
        return recovered

    recorded_prompt = str(entry.get("prompt", ""))
    if usage_out is not None:
        usage_out.update(
            {
                "input_tokens": max(1, len(recorded_prompt) // 4),
                "output_tokens": max(1, len(response) // 4),
                "estimated": True,
            }
        )
    return Usage()


def _anthropic_system_blocks(system: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _call_anthropic(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = _model_for("anthropic")
    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = _anthropic_system_blocks(system)
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    text = "".join(getattr(block, "text", "") for block in response.content)
    return text, _anthropic_usage(response.usage)


def _bedrock_client() -> Any:
    from anthropic import AnthropicBedrockMantle

    return AnthropicBedrockMantle(
        aws_region=os.environ.get("AWS_REGION"),
        aws_profile=os.environ.get("AWS_PROFILE"),
    )


def _call_bedrock(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    client = _bedrock_client()
    model = _model_for("bedrock")
    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = _anthropic_system_blocks(system)
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    text = "".join(getattr(block, "text", "") for block in response.content)
    return text, _anthropic_usage(response.usage)


def _openai_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _call_openai(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    model = _model_for("openai")
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(
        model=model,
        messages=_openai_messages(prompt, system),
        **kwargs,
    )
    return response.choices[0].message.content or "", _openai_usage(response.usage)


class _CustomLLMConfigError(LLMError):
    """Raised when the custom OpenAI-compatible endpoint is underconfigured."""


def _custom_client() -> Any:
    from openai import OpenAI

    base_url = os.environ.get("CUSTOM_LLM_BASE_URL", "").strip()
    if not base_url:
        raise _CustomLLMConfigError(
            "LLM_PROVIDER=custom requires CUSTOM_LLM_BASE_URL, the full "
            "OpenAI-compatible endpoint root including /v1 when the gateway expects it."
        )
    api_key = os.environ.get("CUSTOM_LLM_API_KEY") or "not-required"
    return OpenAI(base_url=base_url, api_key=api_key)


def _custom_model() -> str:
    model = os.environ.get("CUSTOM_LLM_MODEL", "").strip()
    if not model:
        raise _CustomLLMConfigError(
            "LLM_PROVIDER=custom requires CUSTOM_LLM_MODEL, the model name your endpoint serves."
        )
    return model


def _call_custom(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    client = _custom_client()
    model = _custom_model()
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    response = client.chat.completions.create(
        model=model,
        messages=_openai_messages(prompt, system),
        **kwargs,
    )
    return response.choices[0].message.content or "", _openai_usage(response.usage)


def _ollama_client() -> Any:
    from openai import OpenAI

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    return OpenAI(base_url=f"{base_url}/v1", api_key="ollama")


def _call_ollama(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    client = _ollama_client()
    model = _model_for("ollama")
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    response = client.chat.completions.create(
        model=model,
        messages=_openai_messages(prompt, system),
        **kwargs,
    )
    return response.choices[0].message.content or "", _openai_usage(response.usage)


def _claude_cli_usage(raw: dict[str, Any]) -> Usage:
    """Read the usage block from a `claude -p --output-format json` result.

    Field names match the Anthropic API's; absent fields stay `None` per the
    same discipline as `_anthropic_usage`.
    """
    u = raw.get("usage") or {}
    return Usage(
        input_tokens=_int_or_none(u.get("input_tokens")),
        output_tokens=_int_or_none(u.get("output_tokens")),
        cache_read_tokens=_int_or_none(u.get("cache_read_input_tokens")),
        cache_write_tokens=_int_or_none(u.get("cache_creation_input_tokens")),
    )


def _call_claude_cli(prompt: str, system: str | None, json_mode: bool) -> tuple[str, Usage]:
    """Record-time provider: shells out to the local `claude` CLI, headless.

    Uses the CLI's own login, so no API key is involved. Demo-time never
    reaches this function — the demo runs in replay mode — so the dependency
    on Claude Code exists only on the machine that records (hard rule 4).
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    model = os.environ.get("CLAUDE_CLI_MODEL")
    if model:
        cmd += ["--model", model]
    if system:
        cmd += ["--append-system-prompt", system]
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
    except FileNotFoundError as exc:
        raise LLMError(
            "claude CLI not found on PATH; LLM_PROVIDER=claude_cli is record-time only"
        ) from exc
    if proc.returncode != 0:
        raise LLMError(f"claude CLI exited {proc.returncode}: {proc.stderr[-500:]}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude CLI returned non-JSON output: {proc.stdout[:300]}") from exc
    if payload.get("is_error"):
        raise LLMError(f"claude CLI error result: {str(payload.get('result'))[:300]}")
    return str(payload.get("result", "")), _claude_cli_usage(payload)


def _stream_claude_cli(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    """One-shot streamer: the CLI's print mode has no token stream worth
    plumbing, and record-time calls do not need one."""
    text, usage = _call_claude_cli(prompt, system, json_mode)
    if usage.input_tokens is not None:
        usage_out["input_tokens"] = usage.input_tokens
    if usage.output_tokens is not None:
        usage_out["output_tokens"] = usage.output_tokens
    yield text


def _stream_anthropic(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = _model_for("anthropic")
    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = _anthropic_system_blocks(system)
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    with client.messages.stream(
        model=model,
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text
        final = stream.get_final_message()
        usage_out["input_tokens"] = final.usage.input_tokens
        usage_out["output_tokens"] = final.usage.output_tokens


def _stream_bedrock(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    client = _bedrock_client()
    model = _model_for("bedrock")
    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = _anthropic_system_blocks(system)
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"

    with client.messages.stream(
        model=model,
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text
        final = stream.get_final_message()
        usage_out["input_tokens"] = final.usage.input_tokens
        usage_out["output_tokens"] = final.usage.output_tokens


def _stream_openai_compatible(
    *,
    client: Any,
    model: str,
    prompt: str,
    system: str | None,
    json_mode: bool,
    usage_out: dict[str, int],
    include_usage: bool,
) -> Iterator[str]:
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    stream_kwargs: dict[str, Any] = {
        "model": model,
        "messages": _openai_messages(prompt, system),
        "stream": True,
        **kwargs,
    }
    if include_usage:
        stream_kwargs["stream_options"] = {"include_usage": True}

    stream = client.chat.completions.create(**stream_kwargs)
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        usage = getattr(event, "usage", None)
        if usage is not None:
            usage_out["input_tokens"] = usage.prompt_tokens
            usage_out["output_tokens"] = usage.completion_tokens
        if delta:
            yield delta


def _stream_openai(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    yield from _stream_openai_compatible(
        client=client,
        model=_model_for("openai"),
        prompt=prompt,
        system=system,
        json_mode=json_mode,
        usage_out=usage_out,
        include_usage=True,
    )


def _stream_custom(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"
    yield from _stream_openai_compatible(
        client=_custom_client(),
        model=_custom_model(),
        prompt=prompt,
        system=system,
        json_mode=json_mode,
        usage_out=usage_out,
        include_usage=False,
    )


def _stream_ollama(
    prompt: str,
    system: str | None,
    json_mode: bool,
    *,
    usage_out: dict[str, int],
) -> Iterator[str]:
    if json_mode:
        prompt = f"{prompt}{_JSON_INSTRUCTION}"
    yield from _stream_openai_compatible(
        client=_ollama_client(),
        model=_model_for("ollama"),
        prompt=prompt,
        system=system,
        json_mode=json_mode,
        usage_out=usage_out,
        include_usage=False,
    )


_PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "bedrock": _call_bedrock,
    "openai": _call_openai,
    "ollama": _call_ollama,
    "custom": _call_custom,
    "claude_cli": _call_claude_cli,
}

_PROVIDER_STREAMERS = {
    "anthropic": _stream_anthropic,
    "bedrock": _stream_bedrock,
    "openai": _stream_openai,
    "ollama": _stream_ollama,
    "custom": _stream_custom,
    "claude_cli": _stream_claude_cli,
}


def complete(
    prompt: str | PromptLayers,
    *,
    system: str | None = None,
    json_mode: bool = False,
    cache_key: str | None = None,
    retries: int = 2,
    usage_out: dict[str, Any] | None = None,
) -> str:
    """Return a text completion from replay, cache, or the configured live provider.

    `prompt` accepts either a plain string or a `PromptLayers`. Prefer the
    layers: they assemble the request in the fixed, cache-stable order the repo
    decided on (see `common.prompt`), which is what makes the identical prefix
    long enough for prompt caching to pay. A string is treated as the task layer
    alone and is the right shape only for one-off calls.

    An explicit `system` argument wins over one derived from layers, so a caller
    can override deliberately; passing both is otherwise a mistake worth avoiding.
    """
    if isinstance(prompt, PromptLayers):
        layered_system, prompt = prompt.assemble()
        system = system if system is not None else layered_system

    mode = _llm_mode()
    provider = _resolve_provider()
    model = _model_for(provider)
    scenario, beat = scenario_of(cache_key)
    path = _path_for_mode(
        mode=mode,
        provider=provider,
        model=model,
        system=system,
        prompt=prompt,
        cache_key=cache_key,
    )
    t0 = time.monotonic()

    # `record` means "call live and refresh the committed recording", so an
    # existing recording must not short-circuit it — otherwise a bad recording
    # can only be re-rolled by deleting the file by hand.
    is_live_cache = mode == "live"
    entry = None if mode == "record" else _read_entry(path, obey_cache_toggle=is_live_cache)
    if entry is not None:
        response = str(entry["response"])
        usage = _usage_from_entry(entry, response=response, usage_out=usage_out)
        log_call(
            scenario=scenario,
            beat=beat,
            provider=str(entry.get("provider", provider)),
            model=str(entry.get("model", model)),
            cached=True,
            latency_s=time.monotonic() - t0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            success=True,
        )
        return response

    if mode == "replay":
        raise _missing_replay_error(path)

    caller = _PROVIDER_CALLERS[provider]
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response, usage = caller(prompt, system, json_mode)
            _write_entry(
                path,
                prompt=prompt,
                system=system,
                provider=provider,
                model=model,
                response=response,
                usage=usage,
                obey_cache_toggle=is_live_cache,
            )
            if usage_out is not None:
                usage_out.update(usage.as_dict())
            log_call(
                scenario=scenario,
                beat=beat,
                provider=provider,
                model=model,
                cached=False,
                latency_s=time.monotonic() - t0,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                success=True,
            )
            return response
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    log_call(
        scenario=scenario,
        beat=beat,
        provider=provider,
        model=model,
        cached=False,
        latency_s=time.monotonic() - t0,
        input_tokens=None,
        output_tokens=None,
        success=False,
        error=str(last_error),
    )
    raise LLMError(
        f"{provider} call failed after {retries + 1} attempts: {last_error}"
    ) from last_error


def stream_complete(
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = False,
    cache_key: str | None = None,
    retries: int = 2,
    replay_substitutions: dict[str, str] | None = None,
    chunk_delay: float = 0.0,
    usage_out: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Yield text chunks from replay, cache, or the configured live provider."""
    mode = _llm_mode()
    provider = _resolve_provider()
    model = _model_for(provider)
    scenario, beat = scenario_of(cache_key)
    path = _path_for_mode(
        mode=mode,
        provider=provider,
        model=model,
        system=system,
        prompt=prompt,
        cache_key=cache_key,
    )
    t0 = time.monotonic()

    # See `complete`: record refreshes rather than replays.
    is_live_cache = mode == "live"
    entry = None if mode == "record" else _read_entry(path, obey_cache_toggle=is_live_cache)
    if entry is not None:
        yield from _yield_recorded_entry(
            entry,
            path=path,
            provider=provider,
            model=model,
            scenario=scenario,
            beat=beat,
            replay_substitutions=replay_substitutions,
            chunk_delay=chunk_delay,
            started_at=t0,
            usage_out=usage_out,
        )
        return

    if mode == "replay":
        raise _missing_replay_error(path)

    streamer = _PROVIDER_STREAMERS[provider]
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        chunks: list[str] = []
        usage: dict[str, int] = {}
        try:
            for chunk in streamer(prompt, system, json_mode, usage_out=usage):
                chunks.append(chunk)
                yield chunk

            response = "".join(chunks)
            input_tokens = usage.get("input_tokens", max(1, len(prompt) // 4))
            output_tokens = usage.get("output_tokens", max(1, len(response) // 4))
            usage.setdefault("input_tokens", input_tokens)
            usage.setdefault("output_tokens", output_tokens)
            if usage_out is not None:
                usage_out.update(usage)
            _write_entry(
                path,
                prompt=prompt,
                system=system,
                provider=provider,
                model=model,
                response=response,
                # Streaming reports no cache counters: the provider surfaces
                # them only on a final usage object that not every streaming
                # implementation exposes. They stay unset rather than guessed.
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                obey_cache_toggle=is_live_cache,
            )
            log_call(
                scenario=scenario,
                beat=beat,
                provider=provider,
                model=model,
                cached=False,
                latency_s=time.monotonic() - t0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    log_call(
        scenario=scenario,
        beat=beat,
        provider=provider,
        model=model,
        cached=False,
        latency_s=time.monotonic() - t0,
        input_tokens=None,
        output_tokens=None,
        success=False,
        error=str(last_error),
    )
    raise LLMError(
        f"{provider} stream failed after {retries + 1} attempts: {last_error}"
    ) from last_error


def _yield_recorded_entry(
    entry: dict[str, Any],
    *,
    path: Path,
    provider: str,
    model: str,
    scenario: str,
    beat: str,
    replay_substitutions: dict[str, str] | None,
    chunk_delay: float,
    started_at: float,
    usage_out: dict[str, Any] | None,
) -> Iterator[str]:
    response = str(entry["response"])
    for old, new in (replay_substitutions or {}).items():
        response = response.replace(old, new)

    usage = _usage_from_entry(entry, response=response, usage_out=usage_out)
    delay = 0.02 if chunk_delay == 0.0 else chunk_delay
    for idx in range(0, len(response), 40):
        if delay > 0:
            time.sleep(delay)
        yield response[idx : idx + 40]

    log_call(
        scenario=scenario,
        beat=beat,
        provider=str(entry.get("provider", provider)),
        model=str(entry.get("model", model)),
        cached=True,
        latency_s=time.monotonic() - started_at,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        success=True,
    )


def parse_json_response(
    response: str,
    required_keys: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Parse a JSON model response, normalizing model-shape failures to LLMError."""
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model response was not valid JSON: {response[:200]!r}") from exc

    if not isinstance(data, dict):
        raise LLMError(f"model response was valid JSON but not an object: {response[:200]!r}")

    missing = required_keys - data.keys()
    if missing:
        raise LLMError(
            f"model response missing required keys {sorted(missing)}: {response[:200]!r}"
        )
    return data
