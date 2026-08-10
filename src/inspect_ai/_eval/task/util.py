import os
import reprlib
from copy import deepcopy
from fnmatch import fnmatch
from logging import getLogger
from typing import Callable, NamedTuple, cast

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.path import cwd_relative_path
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import Dataset
from inspect_ai.dataset._util import normalise_sample_id
from inspect_ai.model import ChatMessage, ChatMessageUser

from ..task import Task
from .constants import (
    TASK_FILE_ATTR,
    TASK_RUN_DIR_ATTR,
)

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


class SampleIdMatcher(NamedTuple):
    """A `--sample-id` filter: the predicate plus its normalised patterns."""

    matches: Callable[[str | int | None], bool]
    patterns: list[str]


def sample_id_filter(
    sample_id: str | int | list[str] | list[int] | list[str | int],
) -> SampleIdMatcher:
    """Predicate matching a sample id against `sample_id` patterns.

    Ids are normalised (`normalise_sample_id`) and matched with `fnmatch`,
    the same semantics `slice_dataset` applies to a dataset. The normalised
    patterns ride along so callers reporting on the filter (warnings/errors)
    use exactly what the predicate matches.
    """
    sample_ids = sample_id if isinstance(sample_id, list) else [sample_id]
    patterns = [normalise_sample_id(id) for id in sample_ids]

    def matches(id: str | int | None) -> bool:
        return any(fnmatch(normalise_sample_id(id), pat) for pat in patterns)

    return SampleIdMatcher(matches, patterns)


def sample_limit_count(limit: int | tuple[int, int] | None) -> int | None:
    """Number of samples a `limit` option selects (the size of its slice)."""
    if limit is None:
        return None
    return max(0, limit[1] - limit[0]) if isinstance(limit, tuple) else limit


def slice_dataset(
    dataset: Dataset,
    limit: int | tuple[int, int] | None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None,
    dynamic: bool = False,
) -> Dataset:
    """Apply `--limit` / `--sample-id` to a dataset.

    Args:
        dataset: Dataset to slice.
        limit: Count or `(start, stop)` positional range of samples to select.
        sample_id: Sample id pattern(s) to filter by (exclusive with `limit`).
        dynamic: The dataset is a `SampleSource` seed, not the complete sample
            set — samples matching a requested id may be produced while the
            task runs, so unmatched `sample_id` entries neither warn nor error
            (the filter still applies to the seed; the task's dispatcher
            applies it to produced samples).
    """
    if sample_id is not None:
        matcher = sample_id_filter(sample_id)

        # validate all the sample ids and warn if they aren't in the dataset
        if not dynamic:
            all_sample_ids = [normalise_sample_id(sample.id) for sample in dataset]
            for id in matcher.patterns:
                if id not in all_sample_ids:
                    warn_once(
                        logger,
                        f"sample id '{id}' not found in dataset '{dataset.name}'.",
                    )

        # filter the dataset
        filtered = dataset.filter(lambda sample: matcher.matches(sample.id))

        # raise error if we got no hits
        if len(filtered) == 0 and not dynamic:
            filter = ",".join([str(id) for id in matcher.patterns])
            all_sample_ids_raw = [sample.id for sample in dataset]
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


def split_spec(spec: str) -> tuple[str, str | None]:
    parts = spec.rsplit("@", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    else:
        return spec, None
