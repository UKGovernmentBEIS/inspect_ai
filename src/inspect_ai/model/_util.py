from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_info import get_model_info

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask


def resolve_model_roles(
    model_roles: Mapping[str, str | Model] | None,
) -> dict[str, Model] | None:
    if model_roles is not None:
        resolved_model_roles = {
            k: get_model(v, memoize=False) if isinstance(v, str) else v
            for k, v in model_roles.items()
        }
        for k, v in resolved_model_roles.items():
            v._set_role(k)
        return resolved_model_roles
    else:
        return None


def resolve_model(model: str | Model | None) -> Model | None:
    if isinstance(model, str):
        return get_model(model)
    else:
        return model


def resolve_model_costs(
    resolved_tasks: list[ResolvedTask], cost_limit: float | None
) -> None:
    for task in resolved_tasks:
        task_cost_limit = cost_limit if cost_limit is not None else task.task.cost_limit
        if task_cost_limit is None:
            continue

        models: set[Model] = {task.model}
        if task.model_roles:
            models.update(task.model_roles.values())

        missing: list[str] = []
        for model in models:
            model_name = f"{model}"
            info = get_model_info(model_name)
            if info is None or info.cost is None:
                missing.append(model_name)

        if missing:
            raise PrerequisiteError(
                f"cost_limit requires cost data for all models. "
                f"Missing cost data for: {', '.join(missing)}. "
                f"Use set_model_cost() or --model-cost-config to "
                f"configure pricing."
            )
