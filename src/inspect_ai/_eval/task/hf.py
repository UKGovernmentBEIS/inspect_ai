from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

from inspect_ai._eval.task import Task
from inspect_ai._eval.task.epochs import Epochs
from inspect_ai._eval.task.util import split_spec
from inspect_ai._util.error import pip_dependency_error
from inspect_ai.dataset import FieldSpec, hf_dataset


def task_create_from_hf(task_name: str, **kwargs: Any) -> list[Task]:
    """Build a Task from a full config definition (solvers, scorers, dataset, etc.)."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise pip_dependency_error(
            "HuggingFace Dataset Tasks (hf/)", ["huggingface_hub"]
        ) from None

    # see if there is a revision in the repo_id
    repo_id, revision = split_spec(task_name.replace("hf/", ""))
    if revision is None:
        revision = kwargs.get("revision", "main")

    # path to task config
    yaml_path = Path(
        hf_hub_download(
            repo_id=repo_id,
            filename="eval.yaml",
            repo_type="dataset",
            revision=revision,
        )
    )

    with open(yaml_path, "r") as f:
        global_config = yaml.safe_load(f)

    task_configs = global_config["tasks"]

    tasks = []
    for task_config in task_configs:
        # Build dataset
        subset = task_config.get("subset", "default")
        split = task_config.get("splits", "test")
        field_spec = task_config["field_spec"]
        sample_fields = FieldSpec(**field_spec)

        dataset = hf_dataset(
            path=repo_id,
            revision=revision,
            name=subset,
            split=split,
            sample_fields=sample_fields,
        )

        if task_config.get("shuffle_choices", False):
            dataset.shuffle_choices()

        # Build solvers
        solvers = []
        solver_configs = task_config.get("solvers", [])
        solver_module = import_module("inspect_ai.solver")
        for solver_config in solver_configs:
            solver_name = solver_config.get("name")

            if not hasattr(solver_module, solver_name):
                raise ValueError(f"Unknown solver: {solver_name}")

            solver_fn = getattr(solver_module, solver_name)
            solvers.append(solver_fn(**solver_config.get("args", {})))

        # Build scorers
        scorers = []
        scorer_configs = task_config.get("scorers", [])
        scorer_module = import_module("inspect_ai.scorer")
        for scorer_config in scorer_configs:
            scorer_name = scorer_config.get("name")

            if not hasattr(scorer_module, scorer_name):
                raise ValueError(f"Unknown scorer: {scorer_name}")

            scorer_fn = getattr(scorer_module, scorer_name)
            scorers.append(scorer_fn(**scorer_config.get("args", {})))

        # Extract other task parameters
        epochs = task_config.get("epochs", 1)
        epochs_reducer = task_config.get("epochs_reducer", None)

        # Build and return task
        task = Task(
            name=task_name,
            dataset=dataset,
            solver=solvers,
            scorer=scorers,
            epochs=Epochs(epochs, epochs_reducer),
        )

        # Set file attributes
        tasks.append(task)

    return tasks
