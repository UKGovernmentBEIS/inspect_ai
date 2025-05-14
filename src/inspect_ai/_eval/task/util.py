import os
import reprlib
from copy import deepcopy
from logging import getLogger
from typing import cast

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.path import cwd_relative_path
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import Dataset
from inspect_ai.model import ChatMessage, ChatMessageUser

from ..task import Task
from .constants import TASK_FILE_ATTR, TASK_RUN_DIR_ATTR

logger = getLogger(__name__)


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
    sample_id: str | int | list[str] | list[int] | list[str | int] | None,
) -> Dataset:
    def normalise(id: str | int | None) -> str:
        if isinstance(id, str) and id.isdigit():
            id = int(id)
        return id if isinstance(id, str) else str(id).zfill(20)

    if sample_id is not None:
        # reduce to list of normalized sample ids
        sample_ids = sample_id if isinstance(sample_id, list) else [sample_id]
        sample_id = [normalise(id) for id in sample_ids]

        # validate all the sample ids and warn if they aren't in the dataset
        all_sample_ids_raw = [sample.id for sample in dataset]
        all_sample_ids = [normalise(id) for id in all_sample_ids_raw]
        for id in sample_id:
            if id not in all_sample_ids:
                warn_once(
                    logger, f"sample id '{id}' not found in dataset '{dataset.name}'."
                )

        # filter the dataset
        filtered = dataset.filter(lambda sample: normalise(sample.id) in sample_id)

        # raise error if we got no hits
        if len(filtered) == 0:
            filter = ",".join([str(id) for id in sample_id])
            r = reprlib.Repr()
            r.maxlist = 8
            raise PrerequisiteError(
                f"No matches in dataset '{dataset.name}' for sample_id filter '{filter}'\n({dataset.name} ids: {r.repr(all_sample_ids_raw)})"
            )

        return filtered
    else:
        dataset_limit = (
            slice(0, len(dataset))
            if limit is None
            else (slice(*limit) if isinstance(limit, tuple) else slice(0, limit))
        )
        return dataset[dataset_limit]
