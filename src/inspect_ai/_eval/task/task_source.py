"""A dynamic source of tasks for a running eval.

Pass a :class:`TaskSource` instance as the ``tasks`` argument to ``eval()`` to
drive the run from code rather than a fixed task list. The run starts with
``initial_tasks()`` and, after each batch of tasks completes, calls
``next_tasks()`` for the next batch — until it returns ``None``. Override
``sample_complete`` / ``task_complete`` to observe results and decide what to
run next (e.g. an RL loop that spawns follow-up tasks from scores).

``next_tasks()`` is async and may block — awaiting external input or more
results — and returns ``None`` to end the run, so an open-ended "keep producing
until told to stop" loop is expressible. ``initial_tasks()`` is synchronous and
returns immediately (it's the seed the run sets up and starts from, not subject
to that blocking), which is how the run computes concurrency / validates before
execution begins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalLog, EvalSample

    from .task import Task


class TaskSource:
    """Drives a running eval from code: a seed plus result-driven follow-ups.

    Subclass and override the methods you need. The default implementations are
    no-ops / empty, so a bare ``TaskSource`` runs nothing — override at least
    ``initial_tasks`` and ``next_tasks``.
    """

    def initial_tasks(self) -> list["Task"]:
        """Tasks to run first (the seed).

        Called once, synchronously, before the run starts — so it must return
        immediately (no awaiting / blocking). The returned tasks drive the
        run's up-front setup (concurrency, validation) and are the first batch.
        """
        return []

    async def next_tasks(self) -> list["Task"] | None:
        """The next batch of tasks to run, or ``None`` when the run is complete.

        Called after each batch finishes (after that batch's ``sample_complete``
        / ``task_complete`` notifications). May ``await`` — for more results or
        external input — and may block indefinitely; return ``None`` to end the
        run.
        """
        return None

    async def sample_complete(self, sample: "EvalSample") -> None:
        """A sample finished — override to observe its result.

        Fires before the ``next_tasks()`` that follows the sample's batch, so a
        decision in ``next_tasks()`` can use it.
        """

    async def task_complete(self, log: "EvalLog") -> None:
        """A task finished — override to observe its log (samples + scores)."""
