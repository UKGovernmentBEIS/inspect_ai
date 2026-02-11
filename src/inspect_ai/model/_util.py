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
    all_models: set[Model] = set()
    for task in resolved_tasks:
        all_models.add(task.model)
        if task.model_roles:
            all_models.update(task.model_roles.values())

    missing_models: list[str] = []
    for model in all_models:
        model_name = f"{model}"
        info = get_model_info(model_name)
        # Note that we handle info=None here because None is a valid output of get_model_info (e.g. for mock models)
        if info is None or info.cost is None:
            missing_models.append(model_name)

    if not missing_models:
        return

    if cost_limit is not None:
        raise PrerequisiteError(
            f"cost_limit requires cost data for all models. "
            f"Missing cost data for: {', '.join(missing_models)}. Use set_model_cost() or --model-cost-config to configure pricing."
        )

    if len(missing_models) < len(all_models):
        raise PrerequisiteError(
            f"Some models have cost data configured but not all models. Cost data should be provided for either no models, or models being used. "
            f"Missing cost data for: {', '.join(missing_models)}. Use set_model_cost() or --model-cost-config to configure pricing."
        )
