from inspect_ai import Task, eval


def test_log_tags():
    tags = ["foo,bar"]
    log = eval(Task(), tags=tags)[0]
    assert log.eval.tags == tags
