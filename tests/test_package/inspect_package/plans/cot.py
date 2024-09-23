from inspect_ai.solver import Solver, chain, chain_of_thought, generate, solver


@solver
def cot() -> Solver:
    return chain(chain_of_thought(), generate())
