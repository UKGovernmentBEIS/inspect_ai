from __future__ import annotations

import re
from copy import copy
from typing import TYPE_CHECKING, Mapping, Sequence

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_info import _get_model_info_direct

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask

# 'name#N' keys are how list-valued roles are represented in the eval log
# (see model_roles_to_model_roles_config), so they can't be used as role names
_INDEXED_ROLE_PATTERN = re.compile(r".+#\d+$")


def resolve_model_roles(
    model_roles: Mapping[str, str | Model | Sequence[str | Model]] | None,
) -> dict[str, Model | list[Model]] | None:
    if model_roles is not None:
        resolved_model_roles: dict[str, Model | list[Model]] = {}
        for k, v in model_roles.items():
            if _INDEXED_ROLE_PATTERN.match(k):
                raise PrerequisiteError(
                    f"Model role name '{k}' is invalid: names ending in "
                    + "'#<number>' are reserved for representing roles with "
                    + "multiple models. To assign multiple models to a role, "
                    + "pass a list of models for the role."
                )
            if isinstance(v, str | Model):
                resolved_model_roles[k] = _resolve_role_model(k, v)
            else:
                if len(v) == 0:
                    raise PrerequisiteError(
                        f"Model role '{k}' was assigned an empty list "
                        + "(at least one model is required)."
                    )
                models = [_resolve_role_model(k, m) for m in v]
                # a single-model list is equivalent to a single model
                resolved_model_roles[k] = models if len(models) > 1 else models[0]
        return resolved_model_roles
    else:
        return None


def _resolve_role_model(role: str, model: str | Model) -> Model:
    # memoize=False for strings / copy for Model instances so that each role
    # gets a distinct Model instance; otherwise roles sharing the same model
    # collapse onto one object and per-role usage is misattributed (see #4450)
    resolved = (
        get_model(model, memoize=False) if isinstance(model, str) else copy(model)
    )
    resolved._set_role(role)
    return resolved


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
            for role_models in task.model_roles.values():
                models.update(
                    role_models if isinstance(role_models, list) else [role_models]
                )

        missing: list[str] = []
        for model in models:
            model_name = f"{model}"
            # direct (non provider-resolving) lookup: these models are already
            # instantiated, so resolving a provider here would re-instantiate
            # them (reloading local weights)
            info = _get_model_info_direct(model)
            if info is None or info.cost is None:
                missing.append(model_name)

        if missing:
            raise PrerequisiteError(
                f"cost_limit requires cost data for all models. "
                f"Missing cost data for: {', '.join(missing)}. "
                f"Use set_model_cost() or --model-cost-config to "
                f"configure pricing."
            )
