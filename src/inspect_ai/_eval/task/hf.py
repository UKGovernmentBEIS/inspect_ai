from pathlib import Path
from typing import Any

import yaml

from inspect_ai._eval.task import Task
from inspect_ai._eval.task.epochs import Epochs
from inspect_ai._eval.task.util import split_spec
from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai.dataset import FieldSpec, hf_dataset
from inspect_ai.scorer._scorer import ScorerSpec
from inspect_ai.solver._solver import SolverSpec


def task_create_from_hf(task_name: str, **kwargs: Any) -> list[Task]:
    """Build a Task from a full config definition (solvers, scorers, dataset, etc.)."""
    from inspect_ai._eval.loader import scorer_from_spec, solver_from_spec

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
        field_spec = task_config.get("field_spec", None)
        if field_spec is None:
            raise PrerequisiteError(
                "HuggingFace eval task must include a 'field_spec'."
            )
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
        for solver_config in solver_configs:
            solvers.append(
                solver_from_spec(
                    SolverSpec(
                        solver=solver_config.get("name"),
                        args=solver_config.get("args", {}),
                    )
                )
            )

        # Build scorers
        scorers = []
        scorer_configs = task_config.get("scorers", [])
        for scorer_config in scorer_configs:
            scorers.append(
                scorer_from_spec(
                    ScorerSpec(
                        scorer=scorer_config.get("name"),
                    ),
                    task_path=None,
                    **scorer_config.get("args", {}),
                )
            )

        # Extract other task parameters
        epochs = task_config.get("epochs", 1)
        epochs_reducer = task_config.get("epochs_reducer", None)

        # Build and return task
        task = Task(
            name=task_name,
            display_name=task_config.get("name", task_name),
            dataset=dataset,
            solver=solvers,
            scorer=scorers,
            epochs=Epochs(epochs, epochs_reducer),
        )

        # Set file attributes
        tasks.append(task)

    return tasks
