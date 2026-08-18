"""In-memory state for the eval_set scan display.

`scan_init` calls `set_active(scan_dir, spec, summary)` once the scan
dir + spec are known. `scan_eval_sample` calls `push_results(summary,
scanner)` after each `recorder.record()`, passing the cumulative
`Summary` that the recorder just wrote. The Textual `ScanView` widget
reads `get_state()` on its 1Hz tick and renders scout's
`scan_panel(spec, summary, ...)` against it.

This avoids per-tick file I/O — the display reads from in-memory state
populated by the per-sample dispatch path. Concurrent record calls are
fine: each `Summary` snapshot taken under the recorder's lock is
internally consistent, and the state is monotonically richer over time
so a brief out-of-order push is overwritten by the next push.
"""

from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_scout._recorder.summary import Summary
    from inspect_scout._scanspec import ScanSpec


@dataclass
class ScanDisplayState:
    """Latest snapshot of scan state for the Textual display."""

    active: bool = False
    spec: "ScanSpec | None" = None
    summary: "Summary | None" = None
    samples_completed: int = 0
    scan_dir: str | None = None
    scanners_seen: set[str] = field(default_factory=set)


_state = ScanDisplayState()
_lock = Lock()


def reset_state() -> None:
    """Clear all state.

    Called at the start of a fresh scan_init and after scan_finalize to keep the display clean across runs.
    """
    global _state
    with _lock:
        _state = ScanDisplayState()


def set_active(
    *,
    scan_dir: str,
    spec: "ScanSpec",
    summary: "Summary",
    samples_completed: int = 0,
) -> None:
    """Register that a scan is active.

    Called from scan_init once the scan dir + spec are resolved
    (whether fresh or via attach). Sets initial state so the display
    has something to render before the first per-sample push.

    `samples_completed` seeds the progress counter — pass the cumulative
    scan-call count from a prior run when attaching, so the progress
    bar reflects the work already done before this call started.
    """
    global _state
    with _lock:
        _state = ScanDisplayState(
            active=True,
            spec=spec,
            summary=summary,
            samples_completed=samples_completed,
            scan_dir=scan_dir,
            scanners_seen=set(_state.scanners_seen),
        )


def push_results(*, summary: "Summary", scanner: str) -> None:
    """Update state after a successful `recorder.record()`.

    Called from `scan_eval_sample` for each (transcript, scanner) pair.
    `samples_completed` is incremented; `scanners_seen` accumulates the
    distinct scanner names so the display can show progress even before
    every scanner has fired against every transcript.
    """
    global _state
    with _lock:
        if not _state.active:
            # set_active hasn't run yet — drop the push silently. Will
            # be picked up on the next record after init/attach.
            return
        scanners = set(_state.scanners_seen)
        scanners.add(scanner)
        _state = ScanDisplayState(
            active=True,
            spec=_state.spec,
            summary=summary,
            samples_completed=_state.samples_completed + 1,
            scan_dir=_state.scan_dir,
            scanners_seen=scanners,
        )


def mark_completed(n: int) -> None:
    """Bump `samples_completed` by `n` without changing the summary.

    Called from the resume-scan short-circuit path: when a previously-
    recorded transcript is reused (every scanner already has a row for
    its tid), no real scan work happens but the (sample, scanner) pairs
    still count toward this run's expected total. Without this, the
    progress bar would only reflect new scans and stall short of 100%
    on a clean resume.
    """
    global _state
    with _lock:
        if not _state.active:
            return
        _state = ScanDisplayState(
            active=True,
            spec=_state.spec,
            summary=_state.summary,
            samples_completed=_state.samples_completed + n,
            scan_dir=_state.scan_dir,
            scanners_seen=set(_state.scanners_seen),
        )


def get_state() -> ScanDisplayState:
    """Return the current snapshot. Callers must not mutate it.

    The state object is replaced wholesale on each update so this
    function is lock-free; callers see a consistent snapshot.
    """
    return _state
