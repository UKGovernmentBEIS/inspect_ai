from typing import Any, Callable

from pydantic import BaseModel, JsonValue

from inspect_ai._util.json import jsonable_python

ModelCallFilter = Callable[[JsonValue | None, JsonValue], JsonValue]
"""Filter for transforming or removing some values (e.g. images).

The first parmaeter is the key if the value is a dictionary item.
The second parameter is the value. Return a modified value if appropriate.

"""


class ModelCall(BaseModel):
    """Model call (raw request/response data)."""

    request: dict[str, JsonValue]
    """Raw data posted to model."""

    response: dict[str, JsonValue]
    """Raw response data from model."""

    @staticmethod
    def create(
        request: Any, response: Any, filter: ModelCallFilter | None = None
    ) -> "ModelCall":
        """Create a ModelCall object.

        Create a ModelCall from arbitrary request and response objects (they might
        be dataclasses, Pydandic objects, dicts, etc.). Converts all values to
        JSON serialiable (exluding those that can't be)

        Args:
           request (Any): Request object (dict, dataclass, BaseModel, etc.)
           response (Any): Response object (dict, dataclass, BaseModel, etc.)
           filter (ModelCallFilter): Function for filtering model call data.
        """
        request_dict = jsonable_python(request)
        if filter:
            request_dict = _walk_json_value(None, request_dict, filter)
        response_dict = jsonable_python(response)
        if filter:
            response_dict = _walk_json_value(None, response_dict, filter)
        return ModelCall(request=request_dict, response=response_dict)


def _walk_json_value(
    key: JsonValue | None, value: JsonValue, filter: ModelCallFilter
) -> JsonValue:
    value = filter(key, value)
    if isinstance(value, list):
        return [_walk_json_value(None, v, filter) for v in value]
    elif isinstance(value, dict):
        return {k: _walk_json_value(k, v, filter) for k, v in value.items()}
    else:
        return value
