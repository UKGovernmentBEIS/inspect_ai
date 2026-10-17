from typing import Any, TypeVar

from pydantic import model_validator
from pydantic.functional_validators import ModelWrapValidator

ModelT = TypeVar("ModelT")


# @model_validator(mode="wrap") for validators that take `info`, typed against
# ModelWrapValidator alone. mypy fails to infer the model type against pydantic's
# union of wrap validator protocols once it has checked a wrap validator without
# `info` elsewhere (e.g. in mcp>=2.3.0), reporting ModelWrapValidator[Never].
def model_wrap_validator(validator: ModelWrapValidator[ModelT]) -> Any:
    return model_validator(mode="wrap")(validator)
