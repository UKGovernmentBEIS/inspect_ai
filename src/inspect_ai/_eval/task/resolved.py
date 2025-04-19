from dataclasses import dataclass, field
from typing import Any, Set

from inspect_ai._eval.task import Task
from inspect_ai._eval.task.run import EvalSampleSource
from inspect_ai.model import Model
from inspect_ai.util import SandboxEnvironmentSpec


@dataclass(frozen=True)
class ResolvedTask:
    task: Task
    task_args: dict[str, Any]
    task_file: str | None
    model: Model
    model_roles: dict[str, Model] | None
    sandbox: SandboxEnvironmentSpec | None
    sequence: int
    id: str | None = field(default=None)
    sample_source: EvalSampleSource | None = field(default=None)

    @property
    def has_sandbox(self) -> bool:
        if self.sandbox:
            return True
        else:
            return any(
                [True if sample.sandbox else False for sample in self.task.dataset]
            )


def resolved_model_names(tasks: list[ResolvedTask]) -> list[str]:
    models: Set[str] = set()
    for task in tasks:
        models.add(str(task.model))
    return list(models)
