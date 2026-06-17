"""Sample-scoped lifecycle for provider "assistant internal" state.

Providers smuggle wire-level content that doesn't round-trip through
``ChatMessage`` (e.g. Anthropic thinking blocks and server tool spans,
OpenAI Responses tool call params) in per-provider context vars. This
module aggregates their per-sample lifecycle: fresh initialization at
sample start, JSON dump at checkpoint fire, and restore at checkpoint
resume.
"""

from __future__ import annotations

import importlib.util

from pydantic import JsonValue

# `importlib.util.find_spec` walks importer paths (~3 ms per call). Cache
# at module load — package installation can't change during a process
# lifetime, so the result is invariant. Without this, `init_sample_assistant_internal`
# (called once per sample) was costing ~3 s per 500 samples in profiling.
_HAS_OPENAI: bool = importlib.util.find_spec("openai") is not None
_HAS_ANTHROPIC: bool = importlib.util.find_spec("anthropic") is not None


def init_sample_assistant_internal(value: JsonValue | None = None) -> None:
    """Initialize (or restore) per-provider assistant-internal state.

    Called with no ``value`` at sample start to bind fresh per-sample
    instances. Called with a prior :func:`dump_sample_assistant_internal`
    result when resuming from a checkpoint; the restore mutates the
    current instances in place rather than rebinding the context vars —
    the instances were bound in the sample's root task, and an in-place
    update is visible to sibling tasks (e.g. scorers) where a rebind in
    the restoring task would not be.
    """
    assert value is None or isinstance(value, dict)
    if _HAS_OPENAI and (value is None or "openai" in value):
        try:
            from inspect_ai.model._openai_responses import (
                init_sample_openai_assistant_internal,
            )

            init_sample_openai_assistant_internal(
                value["openai"] if value is not None else None
            )
        except ImportError:
            pass

    if _HAS_ANTHROPIC and (value is None or "anthropic" in value):
        try:
            from inspect_ai.model._providers.anthropic import (
                init_sample_anthropic_assistant_internal,
            )

            init_sample_anthropic_assistant_internal(
                value["anthropic"] if value is not None else None
            )
        except ImportError:
            pass


def dump_sample_assistant_internal() -> JsonValue | None:
    """Dump per-provider assistant-internal state as a JSON value.

    Providers with nothing recorded are omitted; returns ``None`` when no
    provider has anything to save (callers skip persistence entirely).
    Restored by passing the result to :func:`init_sample_assistant_internal`.
    """
    dump: dict[str, JsonValue] = {}
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import (
                dump_openai_assistant_internal,
            )

            if (value := dump_openai_assistant_internal()) is not None:
                dump["openai"] = value
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                dump_anthropic_assistant_internal,
            )

            if (value := dump_anthropic_assistant_internal()) is not None:
                dump["anthropic"] = value
        except ImportError:
            pass

    return dump or None
