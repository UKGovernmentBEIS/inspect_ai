from test_helpers.utils import identity_solver

from inspect_ai import Task, eval


def test_no_model():
    log = eval(Task(solver=identity_solver()), model=None)[0]
    assert log.status == "success"
    assert log.eval.model == "none/none"
