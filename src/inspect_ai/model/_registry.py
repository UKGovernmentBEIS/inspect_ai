from typing import Any, Callable, cast

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from ._model import ModelAPI


def modelapi_register(model_type: type[ModelAPI], name: str) -> type[ModelAPI]:
    r"""Register a model api.

    Args:
        model_type (type[Model]): Class deriving from Model
        name (str): API serving this model

    Returns:
        Model API with registry attributes.
    """
    registry_add(
        model_type,
        RegistryInfo(type="modelapi", name=name),
    )
    return model_type


def modelapi(name: str) -> Callable[..., type[ModelAPI]]:
    r"""Decorator for registering model APIs.

    Args:
        name (str): Name of API

    Returns:
        Model API with registry attributes.
    """

    # create_model_wrapper:
    #  (a) Add the type[Model] to the registry using the appropriately
    #      package-namespaced name
    #  (b) Ensure that instances of Model created by type[Model] also
    #      carry registry info.
    def create_model_wrapper(
        wrapped: type[ModelAPI] | Callable[..., type[ModelAPI]], api: str
    ) -> type[ModelAPI]:
        model_api = registry_name(wrapped, api)

        def model_wrapper(*args: Any, **kwargs: Any) -> ModelAPI:
            if not isinstance(wrapped, type):
                model_type = wrapped()
            else:
                model_type = wrapped

            model = model_type(*args, **kwargs)
            registry_tag(
                model_type,
                model,
                RegistryInfo(
                    type="modelapi",
                    name=model_api,
                ),
                *args,
                **kwargs,
            )
            return model

        return modelapi_register(cast(type[ModelAPI], model_wrapper), model_api)

    def wrapper(
        model_type: type[ModelAPI] | Callable[..., type[ModelAPI]],
    ) -> type[ModelAPI]:
        return create_model_wrapper(model_type, name)

    return wrapper
