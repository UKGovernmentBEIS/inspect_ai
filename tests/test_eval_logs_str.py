from inspect_ai._eval.eval import EvalLogs


def test_eval_logs_str_not_empty() -> None:
    logs = EvalLogs([])

    assert str(logs) == "[]"
