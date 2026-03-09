from inspect_ai import Task, eval

TEST_METADATA = {"foo": "bar "}
TEST_TAGS = ["tag1", "tag2"]


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


def test_task_tags():
    log = eval(Task(tags=TEST_TAGS))[0]
    assert sorted(log.eval.tags) == sorted(TEST_TAGS)


def test_eval_tags():
    log = eval(Task(), tags=TEST_TAGS)[0]
    assert sorted(log.eval.tags) == sorted(TEST_TAGS)


def test_task_and_eval_tags():
    task_tags = ["tag1", "tag3"]
    eval_tags = ["tag2", "tag3"]
    log = eval(Task(tags=task_tags), tags=eval_tags)[0]
    assert sorted(log.eval.tags) == ["tag1", "tag2", "tag3"]
