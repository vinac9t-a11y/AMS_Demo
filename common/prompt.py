"""Prompt assembly in a fixed, cache-stable order.

The convention, decided 2026-08-03 (CLAUDE.md § Cache-efficient agent
architecture, decision 1). A prompt is built from five layers, ordered most
stable first:

    rules   -> identical for every call in the repo
    role    -> identical for every call of one stage
    memory  -> identical within a run, slow-changing across runs
    ref     -> changes between work types, not within a run
    task    -> the only layer that genuinely changes per call

Why the order matters. Providers that cache prompts do so on a *prefix*: the
cached span runs from the start of the request up to the last point the text is
identical to a previous request. Put a volatile segment early and everything
after it is a cache miss, however stable that later text is. Ordering the layers
by stability makes the identical prefix as long as it can be, which is the whole
mechanism — a cache read costs roughly a tenth of a fresh input token.

This is a **convention, not a framework**. It is plain string assembly and needs
nothing from any provider; a provider that does no caching is simply unaffected.

The split across `system` and `prompt`. The two most stable layers become the
system prompt, because that is what providers cache most readily and it is
identical across every invocation of a role. The remaining three become the user
prompt, in stability order. Specialization therefore lives in user-prompt
territory, where a change costs a cheap incremental read rather than
invalidating the cached system prompt.

    system  = rules + role
    prompt  = memory + ref + task

**Do not reorder these layers once recordings are committed.** The cache key in
`common.llm` hashes the assembled text by design, so a reordering invalidates
every committed recording at once. See CLAUDE.md § Determinism.
"""

from __future__ import annotations

from dataclasses import dataclass

# The separator between layers. Kept boring and explicit: a blank line renders
# readably in a prompt and is stable across platforms. Do not use os.linesep —
# that would make a recording made on one OS miss on another.
_SEPARATOR = "\n\n"

# Layer order, most stable first. The tuple is the single source of truth: both
# assembly and the tests read it, so the two cannot drift apart.
SYSTEM_LAYERS: tuple[str, ...] = ("rules", "role")
PROMPT_LAYERS: tuple[str, ...] = ("memory", "ref", "task")
LAYER_ORDER: tuple[str, ...] = SYSTEM_LAYERS + PROMPT_LAYERS


def _join(parts: tuple[str | None, ...]) -> str:
    """Join present layers, dropping empty ones without leaving blank gaps."""
    return _SEPARATOR.join(part.strip() for part in parts if part and part.strip())


@dataclass(frozen=True)
class PromptLayers:
    """A prompt expressed as ordered layers rather than one opaque string.

    Every field is optional so a caller can use only the layers it has. An
    absent layer contributes nothing — it does not leave a blank gap, which
    would otherwise make the assembled text depend on which layers happened to
    be set and quietly change the cache key.
    """

    task: str
    rules: str | None = None
    role: str | None = None
    memory: str | None = None
    ref: str | None = None

    @property
    def system(self) -> str | None:
        """The stable prefix: rules + role. `None` when neither is set."""
        return _join((self.rules, self.role)) or None

    @property
    def prompt(self) -> str:
        """The user-prompt body: memory + ref + task, in stability order."""
        return _join((self.memory, self.ref, self.task))

    def assemble(self) -> tuple[str | None, str]:
        """Return `(system, prompt)` ready to hand to `common.llm.complete`."""
        return self.system, self.prompt

    def replace_task(self, task: str) -> PromptLayers:
        """Return a copy with only the task layer changed.

        The common case in a loop: the same rules, role, memory and reference
        applied to the next unit of work. Expressing it this way makes the
        stable prefix obviously stable at the call site.
        """
        return PromptLayers(
            task=task,
            rules=self.rules,
            role=self.role,
            memory=self.memory,
            ref=self.ref,
        )


def stable_prefix_of(layers: PromptLayers) -> str:
    """Return the text expected to be cache-stable across calls of one role.

    Diagnostic, not used in the call path. It answers "how much of this request
    should be a cache read?" — useful when a cache-read-to-write ratio comes out
    lower than expected and the cause is a layer placed in the wrong slot.
    """
    return _join((layers.rules, layers.role, layers.memory, layers.ref))
