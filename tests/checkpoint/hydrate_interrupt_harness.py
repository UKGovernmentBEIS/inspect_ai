"""Harness: resume an eval, then signal it inside the resume copy window.

Run as a script by the interrupted-resume e2e test::

    python hydrate_interrupt_harness.py <log_dir> <retry_from>

Reuses ``resume_kill_harness``'s task/model registrations and wraps
``_resume_copy._copy_payload_data`` (the pass that copies a sample
dir's repos and storage areas) so a real signal — ``SIGNAL_ENV``
selects ``SIGINT`` (what Ctrl-C delivers) or ``SIGKILL`` (an
unanticipated death) — lands *while that data copy is in flight*,
before the checkpoint files that would commit the new dir. The
startup copy (``copy_resume_payloads``) is the first caller, so the
interrupt lands there, before any sample runs.

The wrapped first copy sends the signal and then parks instead of
copying. ``SIGKILL`` never returns from the kill; parking is what pins
a ``SIGINT`` inside the window: under ``asyncio.Runner`` a SIGINT
cancels the root task rather than raising ``KeyboardInterrupt``
synchronously, and the cancellation only lands once a coroutine is
parked at an await — a local test repo copies in milliseconds and wins
that race, whereas the real hazard (a large or remote repo copying for
seconds to minutes) does not. The park stands in for that in-flight
copy; the signal, unwind, and on-disk state are all real.
"""

from __future__ import annotations

import os
import sys

import anyio

import inspect_ai.util._checkpoint._resume_copy as resume_copy
from checkpoint.resume_kill_harness import crash_signal, run_eval

_original_copy_payload_data = resume_copy._copy_payload_data
_fired = False


async def _interrupting_copy_payload_data(
    source_dir: str, destination_dir: str, rels: list[str]
) -> list[str]:
    global _fired
    if not _fired:
        _fired = True
        os.kill(os.getpid(), crash_signal())
        # SIGKILL never gets past the kill; under SIGINT the copy this
        # call would have performed is "still in flight" when the
        # interrupt's cancellation arrives here
        await anyio.sleep_forever()
    return await _original_copy_payload_data(source_dir, destination_dir, rels)


# Distinct exit code asserted by the test: the hook never fired, so the
# child ran an ordinary uninterrupted resume. Guards against a refactor
# that moves the data copy and silently turns the patch into a no-op —
# without this, the test would fail downstream pointing at the product.
HOOK_NEVER_FIRED_EXIT_CODE = 17


def main() -> None:
    resume_copy._copy_payload_data = _interrupting_copy_payload_data
    try:
        run_eval(sys.argv[1], sys.argv[2])
    finally:
        if not _fired:
            print(
                "hydrate_interrupt_harness: the _copy_payload_data hook never fired",
                file=sys.stderr,
            )
            os._exit(HOOK_NEVER_FIRED_EXIT_CODE)


if __name__ == "__main__":
    main()
