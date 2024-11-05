import os
from copy import deepcopy
from typing import cast

from inspect_ai._util.path import cwd_relative_path
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import Dataset
from inspect_ai.model import ChatMessage, ChatMessageUser

from ..task import Task
from .constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR


def sample_messages(sample: Sample) -> list[ChatMessage]:
    if isinstance(sample.input, str):
        return [ChatMessageUser(content=sample.input, source="input")]
    else:
        messages = deepcopy(sample.input)
        for message in messages:
            message.source = "input"
        return messages


def task_run_dir(task: Task) -> str:
    return getattr(task, TASK_RUN_DIR_ATTR, os.getcwd())


def task_file(task: Task, relative: bool = False) -> str | None:
    file = cast(str | None, getattr(task, TASK_FILE_ATTR, None))
    if file:
        if relative:
            return cwd_relative_path(file)
        else:
            return file
    else:
        return None


def slice_dataset(
    dataset: Dataset,
    limit: int | tuple[int, int] | None,
) -> Dataset:
    dataset_limit = (
        slice(0, len(dataset))
        if limit is None
        else (slice(*limit) if isinstance(limit, tuple) else slice(0, limit))
    )
    return dataset[dataset_limit]
