from test_helpers.tasks import empty_task

from inspect_ai._eval.task.constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR


def test_local_module_attr():
    task = empty_task()
    assert getattr(task, TASK_FILE_ATTR, None)
    assert getattr(task, TASK_RUN_DIR_ATTR, None)
