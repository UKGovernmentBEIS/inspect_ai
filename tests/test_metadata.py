from inspect_ai import Task, eval

TEST_METADATA = {"foo": "bar "}


def test_task_metadata():
    log = eval(Task(metadata=TEST_METADATA))[0]
    assert log.eval.metadata == TEST_METADATA


def test_eval_metadata():
    log = eval(Task(), metadata=TEST_METADATA)[0]
    assert log.eval.metadata == TEST_METADATA


def test_task_and_eval_metadata():
    TEST_METADATA_2 = {"bar": "foo"}
    log = eval(Task(metadata=TEST_METADATA_2), metadata=TEST_METADATA)[0]
    assert log.eval.metadata == TEST_METADATA | TEST_METADATA_2
