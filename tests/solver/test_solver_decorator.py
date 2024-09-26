from inspect_ai.solver import Solver, chain, generate, solver, system_message
from inspect_ai.solver._chain import Chain


@solver
def my_solver() -> Solver:
    return chain(system_message("System message"), generate())


def test_solver_decorator():
    x = my_solver()
    assert isinstance(x, Chain)
