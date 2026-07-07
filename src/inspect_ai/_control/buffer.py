"""Log-buffer directives for the control channel.

The state-mutating counterparts to the read surface in
:mod:`inspect_ai._control.state`: flush a task's buffered completed samples to
the (possibly remote, eg. S3) log on demand, and read / retune its sample-buffer
parameters (the latter surfaced through the config directive — see
:mod:`inspect_ai._control.limits`). Both are keyed by task_id — stable across
retry attempts — and resolve to the latest attempt's ``EvalState.live``, the
running ``TaskLogger`` the runner attached via ``register_eval``, so the
control layer stays ignorant of how a buffer is wired.

Returns ``None`` when the task isn't in this process, or its latest attempt has
no live data source (a reused/synthetic eval, or one whose logger was detached
on retry) — flush turns that into a 404; the config view reports the buffer
knobs as absent.
"""

from __future__ import annotations

from typing import Any


async def flush_task_samples(task_id: str) -> dict[str, Any] | None:
    """Flush a task's buffered completed samples to the log.

    Returns ``{"flushed": <count>}`` (samples written), or ``None`` when the
    task's latest attempt isn't flushable in this process.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None or state.live is None:
        return None
    flushed = await state.live.flush_samples()
    return {"flushed": flushed}


def task_buffer_config(
    task_id: str,
    *,
    log_buffer: int | None = None,
    log_shared: int | None = None,
) -> dict[str, Any] | None:
    """Read (and optionally update) a task's sample-buffer parameters.

    With both ``log_buffer`` and ``log_shared`` ``None`` this is a pure read.
    Otherwise the supplied values are applied (``log_buffer`` = completed
    samples buffered before a log write; ``log_shared`` = shared-log sync
    interval in seconds) and the resulting config is returned. Returns the
    config dict (``log_buffer`` / ``pending`` / ``log_shared``), or ``None``
    when the task's latest attempt has no buffer providers in this process.
    """
    from inspect_ai._control.eval_state import latest_eval_for_task

    state = latest_eval_for_task(task_id)
    if state is None or state.live is None:
        return None
    return state.live.buffer_config(log_buffer, log_shared)._asdict()
