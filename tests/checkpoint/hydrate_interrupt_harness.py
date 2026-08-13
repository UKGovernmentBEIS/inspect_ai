"""Harness: resume an eval, then SIGINT it inside hydration's copy window.

Run as a script by the interrupted-hydration e2e test::

    python hydrate_interrupt_harness.py <log_dir> <retry_from>

Reuses ``resume_kill_harness``'s task/model registrations and wraps
``hydrate._fs_copy_repo`` so a real ``SIGINT`` (what Ctrl-C delivers)
lands *while a repo copy is in flight* — after hydration's marker
write, before the checkpoint files that would commit the new dir.

The wrapped first copy sends the signal and then parks instead of
copying. Parking is what pins the interrupt inside the window: under
``asyncio.Runner`` a SIGINT cancels the root task rather than raising
``KeyboardInterrupt`` synchronously, and the cancellation only lands
once a coroutine is parked at an await — a local test repo copies in
milliseconds and wins that race, whereas the real hazard (a large or
remote repo copying for seconds to minutes) does not. The park stands
in for that in-flight copy; the signal, unwind, and on-disk state are
all real.
"""

from __future__ import annotations

import os
import signal
import sys

import anyio

import inspect_ai.util._checkpoint.hydrate as hydrate
from checkpoint.resume_kill_harness import run_eval

_original_fs_copy_repo = hydrate._fs_copy_repo
_fired = False


async def _interrupting_fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> list[str]:
    global _fired
    if not _fired:
        _fired = True
        os.kill(os.getpid(), signal.SIGINT)
        # the copy this call would have performed is "still in flight"
        # when the interrupt's cancellation arrives here
        await anyio.sleep_forever()
    return await _original_fs_copy_repo(old_sample_dir, subpath, new_repo, label=label)


# Distinct exit code asserted by the test: the hook never fired, so the
# child ran an ordinary uninterrupted resume. Guards against a refactor
# that moves the repo copies and silently turns the patch into a no-op —
# without this, the test would fail downstream pointing at the product.
HOOK_NEVER_FIRED_EXIT_CODE = 17


def main() -> None:
    hydrate._fs_copy_repo = _interrupting_fs_copy_repo
    try:
        run_eval(sys.argv[1], sys.argv[2])
    finally:
        if not _fired:
            print(
                "hydrate_interrupt_harness: the _fs_copy_repo hook never fired",
                file=sys.stderr,
            )
            os._exit(HOOK_NEVER_FIRED_EXIT_CODE)


if __name__ == "__main__":
    main()
