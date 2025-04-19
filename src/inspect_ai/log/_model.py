from inspect import isgenerator
from typing import Any, Iterator

from inspect_ai.log._log import EvalModelConfig
from inspect_ai.model._model import Model, get_model


def model_roles_to_model_roles_config(
    model_roles: dict[str, Model] | None,
) -> dict[str, EvalModelConfig] | None:
    if model_roles is not None:
        return {k: model_to_model_config(v) for k, v in model_roles.items()}
    else:
        return None


def model_roles_config_to_model_roles(
    model_config: dict[str, EvalModelConfig] | None,
) -> dict[str, Model] | None:
    if model_config is not None:
        return {k: model_config_to_model(v) for k, v in model_config.items()}
    else:
        return None


def model_to_model_config(model: Model) -> EvalModelConfig:
    return EvalModelConfig(
        model=str(model),
        config=model.config,
        base_url=model.api.base_url,
        args=model_args_for_log(model.model_args),
    )


def model_config_to_model(model_config: EvalModelConfig) -> Model:
    return get_model(
        model=model_config.model,
        config=model_config.config,
        base_url=model_config.base_url,
        memoize=False,
        **model_config.args,
    )


def model_args_for_log(model_args: dict[str, Any]) -> dict[str, Any]:
    # redact authentication oriented model_args
    model_args = model_args.copy()
    if "api_key" in model_args:
        del model_args["api_key"]
    model_args = {k: v for k, v in model_args.items() if not k.startswith("aws_")}

    # don't try to serialise generators
    model_args = {
        k: v
        for k, v in model_args.items()
        if not isgenerator(v) and not isinstance(v, Iterator)
    }
    return model_args
