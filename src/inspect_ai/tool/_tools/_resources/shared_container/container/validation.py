import json
from typing import Mapping, Type, TypeVar

from aiohttp.web import Response
from pydantic import BaseModel, ValidationError

from either import Either, Left, Right

T = TypeVar("T", bound=BaseModel)


def validate_params(
    params: Mapping[str, object], cls: Type[T]
) -> Either[ValidationError, T]:
    try:
        return Right(cls(**params))
    except ValidationError as e:
        return Left(e)


def return_validation_error(error: ValidationError):
    return Response(
        text=json.dumps({"error": "ValidationError", "message": str(error)}),
        content_type="application/json",
    )
