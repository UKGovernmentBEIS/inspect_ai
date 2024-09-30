from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import CachePolicy
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, solver

"""
This example demonstrates how to use the cache feature in `inspect_ai` in your custom solvers
"""


def _dataset():
    return [Sample(input="What is the capital of France?", target="Paris")]


@solver
def solver_with_cache(cache):
    """
    This is our custom solver which will cache the output of the model on calling `generate`.

    How we long we cache the calls for is dependant on the value of the `cache`
    parameter. See the task examples below for more info
    """

    async def solve(state: TaskState, generate: Generate):
        return await generate(state, cache=cache)

    return solve


@task
def cache_example():
    return Task(
        dataset=_dataset(),
        solver=[
            # This will configure a basic cache with default settings, see the
            # defaults in `CachePolicy` for more info.
            solver_with_cache(cache=True),
        ],
        scorer=match(),
    )


@task
def cache_example_with_expiry():
    return Task(
        dataset=_dataset(),
        solver=[
            # Explicitly cache calls for 12 hours
            solver_with_cache(cache=CachePolicy(expiry="12h")),
        ],
        scorer=match(),
    )


@task
def cache_example_never_expires():
    return Task(
        dataset=_dataset(),
        solver=[
            # Cache requests but never expire them
            solver_with_cache(cache=CachePolicy(expiry=None)),
        ],
        scorer=match(),
    )


@task
def cache_example_scoped():
    return Task(
        dataset=_dataset(),
        solver=[
            # Scope the cache key with additional fields and set expiry to a week
            solver_with_cache(
                cache=CachePolicy(
                    scopes={"role": "attacker", "team": "red"},
                    expiry="1W",
                )
            ),
        ],
        scorer=match(),
    )


@task
def cache_example_ignore_epochs():
    return Task(
        dataset=_dataset(),
        solver=[
            # Ignore the epoch when caching. Running this with (for example)
            # `--epochs 20` will still be fast as the first generate call will
            # get cached and re-used by subsequent calls
            solver_with_cache(cache=CachePolicy(per_epoch=False)),
        ],
        scorer=match(),
    )
