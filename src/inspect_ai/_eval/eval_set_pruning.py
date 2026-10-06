"""Skipping construction of tasks a worker's selection does not name.

**The cost this exists to remove.** A worker in selection mode resolves the
whole eval set and then runs one task of it. Resolving means *constructing*
every task, and a dataset loads at construction — so a worker running one task
of a five-hundred-task sweep pays for five hundred datasets to find its own.
That cost is per worker and paid in parallel across the fleet, so per-worker
memory scales with the eval set rather than with the work. This is what makes
a large sweep expensive in a way a small one gives no warning of.

**Why the identifier cannot solve it.** `task_identifier()` hashes a task's
resolved solver plan, model config, and limits — all of which require the
constructed `Task`. By the time an identifier can be computed, the dataset has
already loaded. So the selection carries two coarser facets that *are* knowable
before construction, `registry_name` and `args_hash`, and this module matches on
those.

**Where the interception has to be, and why it is not `eval_set()`.** For the
shape runners actually produce —

    eval_set(tasks=[mbpp(), gsm8k()], model=[...])

— the tasks are constructed while evaluating `eval_set`'s *arguments*, long
before `eval_set()` is entered and reads the selection. There is no hook inside
`eval_set()` early enough. So the `@task` decorator's wrapper is the
interception point, and it reads `INSPECT_EVAL_SET_SELECTION` from the
environment itself rather than being told.

**The safety property, which every decision here is subordinate to.** Pruning
is an optimization and can never change what runs:

- It fires only on a **definite** mismatch. A task is skipped only when its
  `(registry_name, args_hash)` matches no entry in the selection. An unregistered
  task, an unreadable selection, a selection with no facets, an argument list
  that will not bind — all of these prune nothing.
- A placeholder **keeps what it needs to become the real task**, so a wrong
  match is recoverable rather than fatal: the boundary drops placeholders, and
  if that leaves a selected identifier unmatched, the caller materializes them
  and runs anyway. Slow, not broken.
- Layer 1 — the boundary filter in `evalset.py` — remains the sole authority on
  what runs. Nothing here decides anything; it only defers work.

Under-pruning therefore costs time and nothing else, which is the direction
every ambiguous case is resolved in.

**Only an outermost construction is a candidate.** A `@task` function whose body
calls another `@task` function is *composing* rather than enumerating: the inner
call's result becomes the outer task. Pruning it would hand the outer task an
empty dataset while leaving its identifier — which is computed from name,
arguments, solver plan, and model, never from the dataset — matching perfectly.
So the wrapper marks the dynamic extent of a construction and nothing inside one
is pruned. A composed task pays for what it composes, which is work it was going
to do anyway. The counter that tracks this is process-wide rather than
thread-local, deliberately: see `_constructing`.

**What this assumes of a definition, and cannot check.** Skipping a task body
skips its side effects. The definition itself still executes in full, so
module-level and driver-level work — registering models, `set_model_info`,
building `Model` objects — is unaffected; what does not run is the *body* of an
unselected `@task`. A definition where constructing one task is a precondition
for constructing another — a global primed in a task body and read by the next
one — therefore builds the selected task differently from the way capture built
it, and nothing detects that: the dataset is not part of the identifier, so the
altered task still matches. Task bodies being independent of one another is the
one thing pruning needs from a definition and the one thing it cannot verify;
`INSPECT_EVAL_SET_NO_PRUNE` is the answer where that does not hold.

**The hash is not an approximation.** `_args_hash_of_call` computes
`extract_named_params(task_type, False, *args, **kwargs)` — literally the call
`registry_tag` makes a few lines later in the wrapper, whose result becomes
`REGISTRY_PARAMS`, which `resolve_task_args()` reads back and capture hashes.
Same function, same inputs. If that chain ever changes, it changes for both
sides at once.

**Undoing a decision means materializing, not re-resolving**, and the reason is
the same argument-evaluation ordering that put the interception in the wrapper:
by the time anything can react, the caller's own `tasks` list already holds
placeholders, so resolving again resolves the same placeholders. See
`materialize_pruned`.
"""

import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from inspect_ai._util.registry import extract_named_params

from .eval_set_manifest import task_args_hash
from .eval_set_selection import INSPECT_EVAL_SET_SELECTION

INSPECT_EVAL_SET_NO_PRUNE = "INSPECT_EVAL_SET_NO_PRUNE"
"""Set to disable early pruning. The escape hatch for a suspected pruning bug: a run can be compared with and without it without downgrading inspect, and a difference in *results* is a bug report — there should never be one."""

TASK_PLACEHOLDER_ATTR = "__task_placeholder__"
"""Attribute marking a `Task` that was never really constructed. Read by `evalset.py` at the boundary."""


@dataclass(frozen=True)
class TaskPlaceholder:
    """What a pruned task carries in place of itself.

    Enough to undo the decision, and nothing in the normal path reads it: it exists so that a pruning bug degrades to slowness rather than to a failed run.

    `construct` is the decorator's own build-and-tag closure rather than the bare task function, and that distinction is load-bearing. Calling the raw function would produce a `Task` with no registry tag, so `resolve_task_args` would read `{}` and its identifier would be a different task's — a wrong answer arrived at while recovering from a wrong answer.
    """

    construct: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    def materialize(self) -> Any:
        """Build the task after all, paying the cost that was skipped."""
        return self.construct(*self.args, **self.kwargs)


_UNLOADED = object()
"""Distinct from `None`, which is a legitimate loaded state meaning *no selection*."""

_constructing = 0
"""How many task constructions are in progress, process-wide.

**Process-wide rather than thread-local, and the direction of the error is the whole reason.** A thread-local counter reads zero in any thread that did not open the construction — so a task body that builds its inner task through a `ThreadPoolExecutor` would have it pruned, which is the *over*-pruning this module is not allowed to do. A shared counter errs the other way: two genuinely independent constructions overlapping on different threads leave one of them un-pruned, which costs time. `contextvars` is not the alternative it looks like, since a `ContextVar` does not propagate into a pool thread either.
"""

_construction_lock = threading.Lock()
"""Guards `_constructing`, whose increment and decrement are not atomic. Held for two statements per task construction, which is nothing beside constructing one."""


@contextmanager
def task_construction() -> Iterator[None]:
    """Mark the dynamic extent of building one task.

    Entered by the `@task` wrapper around the call to the task function. A `@task` call made while this is held is a task being *composed into* the one under construction rather than an independent entry in the eval set, and pruning it would empty a task that was selected — so `prune_task_call` declines inside it. See the module docstring, *Only an outermost construction is a candidate*.
    """
    global _constructing
    with _construction_lock:
        _constructing += 1
    try:
        yield
    finally:
        with _construction_lock:
            _constructing -= 1


class _Pruner:
    """The selection's `(registry_name, args_hash)` pairs, read lazily and cached.

    Lazy because the environment is read at first task construction rather than at import: a definition may set up its own environment, and nothing here should force an ordering on that. Cached because a definition with two hundred `@task` calls must not read and parse the selection two hundred times.

    **Cached against the environment variable's value rather than against "have I looked yet".** A worker sets the variable before it starts, so in production the first read is the only read either way. But a process that constructs a task *before* the selection is set — capture and selection in one interpreter, which is how the tests drive this — would otherwise cache *no selection* and never look again, silently disabling pruning. Keying on the value costs one `os.environ.get` per task construction and removes the ordering assumption entirely.
    """

    def __init__(self) -> None:
        self._key: object = _UNLOADED
        self._facets: set[tuple[str, str]] = set()
        self._pruned = False
        self._disabled = False

    def reset(self) -> None:
        """Forget the cached selection. For tests, which change the environment between cases."""
        self._key = _UNLOADED
        self._facets = set()
        self._pruned = False
        self._disabled = False

    def disable(self) -> None:
        """Stop pruning for the rest of this process.

        The undo. A resolution that pruned and then could not match a selected identifier is re-run under this, which is what makes a wrong pruning decision cost time rather than the run. Sticky against the environment-keyed reload below, because it is an explicit decision rather than an observation.
        """
        self._disabled = True
        self._facets = set()

    @property
    def pruned_anything(self) -> bool:
        """Whether any task has been skipped in this process.

        What lets the boundary tell *the definition changed* apart from *pruning was wrong*: an unmatched identifier with nothing pruned is genuine drift, and re-resolving would only produce the same answer more slowly.
        """
        return self._pruned

    def _facets_now(self) -> set[tuple[str, str]]:
        """The pairs to prune against, re-reading if the selection has changed."""
        if self._disabled:
            return set()
        key = os.environ.get(INSPECT_EVAL_SET_SELECTION, "").strip()
        if key != self._key:
            self._key = key
            self._facets = self._load(key)
        return self._facets

    def _load(self, key: str) -> set[tuple[str, str]]:
        # every failure path here returns an empty set, which prunes nothing.
        # This function is deliberately incapable of raising: it runs inside
        # task construction, where an exception would surface as a failure of
        # the user's own definition, and `eval_set()` is a few frames away from
        # reading the same file and reporting whatever is wrong with it
        # properly.
        if not key or os.environ.get(INSPECT_EVAL_SET_NO_PRUNE, "").strip():
            return set()
        try:
            from .eval_set_selection import read_eval_set_selection

            selection = read_eval_set_selection(key)
        except Exception:
            return set()

        facets = {
            (entry.registry_name, entry.args_hash)
            for entry in selection.tasks
            if entry.registry_name is not None and entry.args_hash is not None
        }
        # all or nothing. A selection where only some entries carry facets is a
        # runner mid-upgrade or a runner with a bug, and pruning on a partial
        # set would skip exactly the tasks whose facets were omitted
        return facets if len(facets) == len(selection.tasks) else set()

    def should_prune(self, registry_name: str, args_hash: str) -> bool:
        """Whether a task with these facets is definitely not selected."""
        facets = self._facets_now()
        if not facets or (registry_name, args_hash) in facets:
            return False
        self._pruned = True
        return True

    def name_is_selected(self, registry_name: str) -> bool:
        """Whether any selected task has this registry name, ignoring args.

        The weaker question, for the resolver: it knows a name before it imports or constructs anything, but not the arguments a task will be created with. `True` when nothing is being pruned, so a caller can use it as a plain filter.
        """
        facets = self._facets_now()
        return not facets or any(name == registry_name for name, _ in facets)

    def active(self) -> bool:
        """Whether there is a selection with usable facets to prune against."""
        return bool(self._facets_now())


_pruner = _Pruner()


def reset_pruning() -> None:
    """Forget the cached selection (tests)."""
    _pruner.reset()


def disable_pruning() -> None:
    """Stop pruning for the rest of this process, so a resolution can be retried honestly."""
    _pruner.disable()


def is_placeholder(task: object) -> bool:
    """Whether this task was skipped rather than constructed."""
    return getattr(task, TASK_PLACEHOLDER_ATTR, None) is not None


def pruning_active() -> bool:
    """Whether a selection with usable pruning facets is in force."""
    return _pruner.active()


def pruned_anything() -> bool:
    """Whether any task construction has been skipped in this process."""
    return _pruner.pruned_anything


def task_name_selected(registry_name: str) -> bool:
    """Whether a registry name appears in the selection at all.

    `True` when nothing is being pruned, so a caller can use this as a plain filter without checking first.
    """
    return _pruner.name_is_selected(registry_name)


def prune_task_call(
    task_type: Callable[..., Any],
    registry_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> bool:
    """Whether a `@task` call can be skipped.

    Args:
        task_type: The undecorated task function.
        registry_name: Its registered name — the name the selection carries, and the only name knowable before the function body runs.
        args: Positional arguments of this call.
        kwargs: Keyword arguments of this call.

    Returns:
        Whether to return a placeholder instead of constructing the task. `False` on any uncertainty at all, and always for a task being constructed inside another one.
    """
    if _constructing:
        return False
    if not _pruner.active():
        return False
    args_hash = _args_hash_of_call(task_type, args, kwargs)
    if args_hash is None:
        return False
    return _pruner.should_prune(registry_name, args_hash)


def materialize_pruned(tasks: Any) -> Any:
    """Replace any placeholder in a task list with the task it stood in for.

    **What the retry needs and re-resolution cannot provide.** For the shape runners produce, `eval_set(tasks=[foo(), bar()])`, the placeholders were created while evaluating the argument list — so by the time anything can react to a bad decision, the caller's own `tasks` already holds them, and resolving again just resolves the same placeholder objects. Undoing the decision means building the tasks that were skipped.

    Args:
        tasks: Whatever was passed as `tasks`. Anything that is not a sequence of tasks is returned unchanged — a string spec or a registry name is re-read from scratch on the next resolution, so it needs nothing here. Any sequence comes back as a list, since `eval_set` accepts one and the recovery path is not the place to preserve a container type.

    Returns:
        The tasks, with placeholders materialized.
    """
    # a str is a Sequence and is one spec rather than a list of them
    if isinstance(tasks, Sequence) and not isinstance(tasks, str):
        return [_materialized(task) for task in tasks]
    return _materialized(tasks)


def _materialized(task: Any) -> Any:
    placeholder = getattr(task, TASK_PLACEHOLDER_ATTR, None)
    return (
        placeholder.materialize() if isinstance(placeholder, TaskPlaceholder) else task
    )


def _args_hash_of_call(
    task_type: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str | None:
    """Hash this call's arguments the way capture hashed the same task's.

    The equality this rests on is exact rather than parallel: `registry_tag` records `extract_named_params(task_type, False, *args, **kwargs)` as the task's registry params, `resolve_task_args()` reads those back, and capture hashes *that*. This calls the same function with the same arguments.

    Returns:
        The hash, or `None` where the arguments cannot be bound or serialized — in which case nothing is pruned and the real call raises whatever it was going to raise.
    """
    try:
        return task_args_hash(extract_named_params(task_type, False, *args, **kwargs))
    except Exception:
        return None
