from typing import Mapping

from inspect_ai.model._model import Model, get_model


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
