"""Backward-compatible call adapters for the `Compact` protocol.

External implementations may predate the additions of `force` to
`compact_input` and `input` (plus async) to `record_output`. These helpers
sniff the user's signature once (cached by bound-method id) and dispatch
to whichever shape they implement.
"""

import inspect
from inspect import Parameter
from typing import Any

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model_output import ModelOutput

from .types import Compact

_sig_cache: dict[int, inspect.Signature] = {}


def _sig(fn: Any) -> inspect.Signature:
    # Bound methods get a fresh id() per attribute access, so key on the
    # underlying function (`__func__`) when present — stable across calls.
    target = getattr(fn, "__func__", fn)
    key = id(target)
    sig = _sig_cache.get(key)
    if sig is None:
        sig = inspect.signature(fn)
        _sig_cache[key] = sig
    return sig


def _accepts(sig: inspect.Signature, name: str) -> bool:
    params = sig.parameters
    if name in params:
        return True
    return any(p.kind is Parameter.VAR_KEYWORD for p in params.values())


def _positional_count(sig: inspect.Signature) -> int:
    return sum(
        1
        for p in sig.parameters.values()
        if p.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    )


async def compact_input_compat(
    compact: Compact,
    messages: list[ChatMessage],
    *,
    force: bool = False,
) -> tuple[list[ChatMessage], ChatMessageUser | None]:
    sig = _sig(compact.compact_input)
    if _accepts(sig, "force"):
        return await compact.compact_input(messages, force=force)
    return await compact.compact_input(messages)


async def record_output_compat(
    compact: Compact,
    input: list[ChatMessage],
    output: ModelOutput,
) -> None:
    sig = _sig(compact.record_output)
    accepts_input = _accepts(sig, "input") or _positional_count(sig) >= 2
    if accepts_input:
        result = compact.record_output(input, output)
    else:
        result = compact.record_output(output)  # type: ignore[call-arg,arg-type]
    if inspect.isawaitable(result):
        await result
