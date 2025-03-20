from inspect_ai.log._log import EvalModelConfig
from inspect_ai.model._model import Model, get_model


def model_to_model_config(model: Model) -> EvalModelConfig:
    return EvalModelConfig(
        model=str(model),
        config=model.config,
        base_url=model.api.base_url,
        args=model.model_args,
    )


def model_config_to_model(model_config: EvalModelConfig) -> Model:
    return get_model(
        model=model_config.model,
        config=model_config.config,
        base_url=model_config.base_url,
        model_args=model_config.args,
    )
