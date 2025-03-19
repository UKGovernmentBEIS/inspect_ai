from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails
from returns.result import Failure, Result, Success

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


def validate_params(
    params: dict[str, object], cls: Type[BaseModelT]
) -> Result[BaseModelT, ValidationError]:
    """
    Validates the given parameters using the provided pydantic model class.

    Args:
      params (JSONDict): A dictionary of parameters to validate.
      cls (Type[TBaseModel]): The class type to instantiate with the given parameters.

    Returns:
      Result[TBaseModel, ValidationError]: A Success result containing the instantiated class
      if validation is successful, or a Failure result containing the ValidationError if validation fails.
    """
    try:
        return Success(cls.model_validate(params, strict=True))
    except ValidationError as error:
        return Failure(error)


def pretty_validation_error(error: ValidationError) -> str:
    return "Invalid parameters: " + "\n".join(
        [_pretty_message(err) for err in error.errors()]
    )


def _pretty_message(error: ErrorDetails) -> str:
    locs = error["loc"]
    return (
        f"'{'.'.join([str(loc) for loc in locs])}' {error['msg']}"
        if locs
        else error["msg"]
    )
