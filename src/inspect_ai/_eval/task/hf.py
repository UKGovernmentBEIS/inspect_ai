from dataclasses import dataclass, field
from pathlib import Path
from string import ascii_uppercase
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from inspect_ai._eval.task import Task
from inspect_ai._eval.task.epochs import Epochs
from inspect_ai._eval.task.util import split_spec
from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai.dataset import FieldSpec, Sample, hf_dataset
from inspect_ai.dataset._dataset import DatasetRecord
from inspect_ai.scorer._scorer import Scorer, ScorerSpec
from inspect_ai.solver._solver import Solver, SolverSpec


class TaskComponent(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


@dataclass
class FieldSpecHF(FieldSpec):
    choices: str | list[str] | None = field(default=None)  # type: ignore[assignment]
    """ Overriding the FieldSpec to fit field spec coming from the eval.yaml """


class HFTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None)
    config: str = Field(default="default")
    split: str = Field(default="test")
    field_spec: FieldSpecHF
    shuffle_choices: bool | None = Field(default=None)
    epochs: int = Field(default=1)
    epoch_reducer: str | None = Field(default=None)
    solvers: list[TaskComponent] = Field(default_factory=list)
    scorers: list[TaskComponent] = Field(default_factory=list)


def task_create_from_hf(task_name: str, **kwargs: Any) -> list[Task]:
    """Build a Task from a full config definition (solvers, scorers, dataset, etc.)."""
    from inspect_ai._eval.loader import scorer_from_spec, solver_from_spec

    try:
        from huggingface_hub import errors as hf_errors
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise pip_dependency_error(
            "HuggingFace Dataset Tasks (hf/)", ["huggingface_hub"]
        ) from None

    # see if there is a revision in the repo_id (otherwise use task arg)
    task_spec, revision = split_spec(task_name.replace("hf/", ""))
    if revision is None:
        revision = kwargs.get("revision", "main")

    # see if there is a name in the spec or just a repo id
    # (if there is a name we'll use it to filter the task list)
    repo_id, name = parse_task_spec(task_spec)

    # load config
    try:
        yaml_path = Path(
            hf_hub_download(
                repo_id=repo_id,
                filename="eval.yaml",
                repo_type="dataset",
                revision=revision,
            )
        )
    except hf_errors.RemoteEntryNotFoundError:
        raise PrerequisiteError(
            f"No 'eval.yaml' file found for Hugging Face Dataset '{repo_id}'"
        )

    # read tasks
    with open(yaml_path, "r") as f:
        global_config = yaml.safe_load(f)
    task_configs = global_config.get("tasks", None)
    if task_configs is None:
        raise PrerequisiteError("eval.yaml does not include 'tasks' field.")

    tasks: list[Task] = []
    for task_config in task_configs:
        # validate config
        hf_task = HFTask.model_validate(task_config)

        # if there is more than one task then 'id' is required
        if len(task_configs) > 1 and hf_task.id is None:
            raise PrerequisiteError(
                "Task 'id' field is required if there are more than 1 tasks in 'eval.yaml'"
            )

        # filter on id if specified
        if name is not None and hf_task.id != name:
            continue

        def record_to_sample_hf(
            record: DatasetRecord, field_spec: FieldSpecHF = hf_task.field_spec
        ) -> Sample:
            return _record_to_sample_hf(record, field_spec)

        # create dataset
        dataset = hf_dataset(
            path=repo_id,
            revision=revision,
            name=hf_task.config,
            split=hf_task.split,
            sample_fields=record_to_sample_hf,
        )

        # shuffle choides if requested
        if hf_task.shuffle_choices:
            dataset.shuffle_choices()

        # Build solvers
        solvers: list[Solver] = []
        for solver in hf_task.solvers:
            solvers.append(
                solver_from_spec(
                    SolverSpec(
                        solver=solver.name,
                        args=solver.args,
                    )
                )
            )

        # Build scorers
        scorers: list[Scorer] = []
        for scorer in hf_task.scorers:
            scorers.append(
                scorer_from_spec(
                    ScorerSpec(
                        scorer=scorer.name,
                    ),
                    task_path=None,
                    **scorer.args,
                )
            )

        # Build and return task (use id disambiguator if more than 1 task)
        task = Task(
            name=f"{task_name}/{hf_task.id}" if len(task_configs) > 1 else task_name,
            dataset=dataset,
            solver=solvers,
            scorer=scorers,
            epochs=Epochs(hf_task.epochs, hf_task.epoch_reducer),
        )

        # Set file attributes
        tasks.append(task)

    # raise if there are no tasks
    if len(tasks) == 0:
        raise PrerequisiteError(f"No tasks matching '{task_name}' were found.")

    return tasks


def parse_task_spec(task_spec: str) -> tuple[str, str | None]:
    parts = task_spec.split("/")

    if len(parts) == 2:
        repo_id = task_spec
        taskname: str | None = None
    elif len(parts) == 3:
        repo_id = f"{parts[0]}/{parts[1]}"
        taskname = parts[2]
    else:
        raise ValueError(f"Expected 2 or 3 components, got {len(parts)}")

    return repo_id, taskname


def _sanitize_target(record: DatasetRecord, target: str) -> str:
    # if the target is a literal, return the value after the colon without checking the record.
    if target.startswith("literal:"):
        target = target.split(":")[1]
        return target

    # otherwise, get the target from the record and convert to a letter if it's a number.
    target = record[target]
    if isinstance(target, int):
        target = ascii_uppercase[target]

    return target


def _sanitize_choices(
    record: DatasetRecord, choices: str | list[str] | None
) -> Any | None:
    # if the choices are a list, return the values from the record.
    if choices is None:
        return None

    if isinstance(choices, list):
        return [record[choice] for choice in choices]
    else:
        return record[choices]


def _record_to_sample_hf(record: DatasetRecord, field_spec: FieldSpecHF) -> Sample:
    sample_kwargs = {}
    sample_kwargs["input"] = record[field_spec.input]

    if target := _sanitize_target(record, field_spec.target):
        sample_kwargs["target"] = target

    if choices := _sanitize_choices(record, field_spec.choices):
        sample_kwargs["choices"] = choices

    if metadata_keys := field_spec.metadata:
        assert isinstance(metadata_keys, list)  # to appease mypy
        metadata = {name: record[name] for name in metadata_keys}
        sample_kwargs["metadata"] = metadata

    return Sample(**sample_kwargs)
