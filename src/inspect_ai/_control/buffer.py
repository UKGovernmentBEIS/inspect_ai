"""Buffer directives for the control channel.

The state-mutating counterparts to the read surface in
:mod:`inspect_ai._control.state`: flush an eval's buffered completed samples to
the (possibly remote, eg. S3) log on demand, and read / retune its sample-buffer
parameters. Both reach the live eval through ``EvalState.live`` — the running ``TaskLogger``
the runner attached to the process-global
:class:`~inspect_ai._control.eval_state.EvalState` via ``register_eval`` — so the
control layer stays ignorant of how a buffer is wired.

Returns ``None`` when the eval isn't in this process, or has no live data source
(a reused/synthetic eval, or one whose logger was detached on retry) — the
endpoint turns that into a 404.
"""

from __future__ import annotations

from typing import Any


async def flush_eval_samples(eval_id: str) -> dict[str, Any] | None:
    """Flush an eval's buffered completed samples to the log.

    Returns ``{"flushed": <count>}`` (samples written), or ``None`` when the
    eval isn't flushable in this process.
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or state.live is None:
        return None
    flushed = await state.live.flush_samples()
    return {"flushed": flushed}


async def eval_buffer_config(
    eval_id: str,
    *,
    log_buffer: int | None = None,
    log_shared: int | None = None,
) -> dict[str, Any] | None:
    """Read (and optionally update) an eval's sample-buffer parameters.

    With both ``log_buffer`` and ``log_shared`` ``None`` this is a pure read.
    Otherwise the supplied values are applied (``log_buffer`` = completed
    samples buffered before a log write; ``log_shared`` = shared-log sync
    interval in seconds) and the resulting config is returned. Returns the
    config dict (``log_buffer`` / ``pending`` / ``log_shared``), or ``None``
    when the eval has no buffer providers in this process.
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or state.live is None:
        return None
    return state.live.buffer_config(log_buffer, log_shared)._asdict()
