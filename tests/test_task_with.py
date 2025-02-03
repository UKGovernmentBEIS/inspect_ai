from test_helpers.tasks import minimal_task

from inspect_ai import task_with


def test_task_with_add_options():
    task = task_with(minimal_task(), time_limit=30)
    assert task.time_limit == 30
    assert task.metadata is not None


def test_task_with_remove_options():
    task = task_with(
        minimal_task(),
        scorer=None,
    )
    assert task.scorer is None
    assert task.metadata is not None


def test_task_with_edit_options():
    task = task_with(
        minimal_task(),
        metadata={"foo": "bar"},
    )
    assert task.metadata == {"foo": "bar"}


def test_task_with_name_option():
    task = task_with(minimal_task(), name="changed")
    assert task.name == "changed"
