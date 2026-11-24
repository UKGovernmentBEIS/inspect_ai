"""Monitor state a sidecar keeps, copied into the sample store before Inspect's scorers read it."""

from typing import TYPE_CHECKING

from ._endpoint import SentinelProxyError
from ._task import MONITOR_STATE_COPY, attempt_number, task_sidecars

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample
    from inspect_ai.solver._task_state import TaskState
    from inspect_ai.util._store import Store


async def copy_sidecar_monitor_state(
    state: "TaskState", active: "ActiveSample | None" = None
) -> None:
    """Copy the monitor state of the sidecars the running attempt's calls went through into its sample store, before it is scored.

    Args:
        state: The sample's state.
        active: The running sample, where it isn't the caller's own, as for interim scoring.

    Raises:
        SentinelProxyError: If the copy failed, so the sample is not scored: a scorer would otherwise read default values that look like a sample in which nothing was flagged. State a sidecar withholds on purpose, with `--no-eval-results`, is no failure.
    """
    from inspect_ai.log._samples import sample_active

    sidecars = task_sidecars(active.eval_id if active is not None else None)
    sample = active or sample_active()
    if sidecars is not None and sample is not None:
        await sidecars.copy_monitor_state(
            state.uuid, attempt_number(sample), state.store
        )


async def save_sidecar_monitor_state(
    state: "TaskState", cancelled: bool = False
) -> None:
    """Copy the monitor state into the store of a sample saved without being scored, as a failed sample is.

    Inside Inspect, the sample store holds the monitor state when the sample is saved, so a later `inspect score` reads it. The sample has already failed, so a copy that fails doesn't fail it again: the marker in the sample store says why there is no state.

    A cancelled sample's teardown can't be interrupted, so it doesn't wait on a sidecar that may not answer: the marker says the state wasn't copied.
    """
    if cancelled:
        from inspect_ai.log._samples import sample_active

        sidecars = task_sidecars()
        sample = sample_active()
        if sidecars is not None and sample is not None:
            sidecars.skip_monitor_state_copy(
                state.uuid,
                attempt_number(sample),
                state.store,
                "the sample was cancelled before it was copied",
            )
        return
    try:
        await copy_sidecar_monitor_state(state)
    except SentinelProxyError:
        pass


def monitor_state_missing(store: "Store") -> str | None:
    """Why the monitor state of a sample saved in a log is missing, or None if it was copied, is withheld on purpose, or no sidecar kept any.

    Read before a saved sample is scored again, as by `inspect score`, when no copy is possible any more: the marker the copy left says whether it succeeded.
    """
    copy = store.get(MONITOR_STATE_COPY)
    if isinstance(copy, dict) and not copy.get("copied") and not copy.get("withheld"):
        return str(copy.get("reason") or "the copy from the sidecar failed")
    return None
