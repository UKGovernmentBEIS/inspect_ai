import json
from typing import Any, Callable, cast

from pydantic import BaseModel, Field, JsonValue, PrivateAttr

from inspect_ai._util.json import jsonable_python


def as_error_response(body: object | None) -> dict[str, JsonValue]:
    """Convert an exception body to a safe response dict for ModelCall."""
    if isinstance(body, dict):
        return cast(dict[str, JsonValue], jsonable_python(body))
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
            return {"body": parsed}
        except json.JSONDecodeError:
            return {"body": body}
    return {"body": jsonable_python(body)}


ModelCallFilter = Callable[[JsonValue | None, JsonValue], JsonValue]
"""Filter for transforming or removing some values (e.g. images).

The first parmaeter is the key if the value is a dictionary item.
The second parameter is the value. Return a modified value if appropriate.

"""


class ModelCall(BaseModel):
    """Model call (raw request/response data)."""

    request: dict[str, JsonValue]
    """Raw data posted to model."""

    response: dict[str, JsonValue] | None = Field(default=None)
    """Raw response data from model (None if call is still pending)."""

    time: float | None = Field(default=None)
    """Time taken for underlying model call."""

    _filter: ModelCallFilter | None = PrivateAttr(default=None)

    @staticmethod
    def create(
        request: Any,
        response: Any | None,
        filter: ModelCallFilter | None = None,
        time: float | None = None,
    ) -> "ModelCall":
        """Create a ModelCall object.

        Create a ModelCall from arbitrary request and response objects (they might
        be dataclasses, Pydandic objects, dicts, etc.). Converts all values to
        JSON serialiable (exluding those that can't be)

        Args:
           request (Any): Request object (dict, dataclass, BaseModel, etc.)
           response (Any | None): Response object (dict, dataclass, BaseModel, etc.),
               or None if the call is still pending.
           filter (ModelCallFilter): Function for filtering model call data.
           time: Time taken for underlying ModelCall
        """
        request_dict: dict[str, JsonValue] = jsonable_python(request)
        if filter:
            request_dict = cast(
                dict[str, JsonValue], _walk_json_value(None, request_dict, filter)
            )

        response_dict: dict[str, JsonValue] | None = None
        if response is not None:
            response_dict = jsonable_python(response)
            if filter:
                response_dict = cast(
                    dict[str, JsonValue], _walk_json_value(None, response_dict, filter)
                )

        return ModelCall(
            request=request_dict, response=response_dict, time=time, _filter=filter
        )

    def set_response(self, response: Any, time: float | None = None) -> None:
        response_dict = jsonable_python(response)
        if self._filter:
            response_dict = cast(
                dict[str, JsonValue],
                _walk_json_value(None, response_dict, self._filter),
            )
        self.response = response_dict
        self.time = time


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
