from copy import deepcopy

from inspect_ai.solver import (
    Generate,
    TaskState,
    chain,
    solver,
)


@solver
def identity():
    async def solve(state: TaskState, _generate: Generate):
        return state

    return solve


def test_solver_chain():
    solver1 = identity()
    chain1 = chain(identity(), identity(), identity())
    assert len(chain(solver1, chain1)) == 4

    chain2 = chain(solver1, chain1, chain(identity(), identity()))
    assert len(chain2) == 6

    assert len(chain(chain2, deepcopy(chain2))) == 12
