import json
import traceback
from typing import Awaitable, Callable, ParamSpec, Type, TypeVar

import httpx
import jsonrpcserver
from httpx import (
    URL,
    AsyncClient,
    ConnectError,
    ConnectTimeout,
    HTTPStatusError,
    ReadTimeout,
)
from jsonrpcserver import method
from pydantic import BaseModel, ValidationError
from returns.result import Failure, Success
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_tool_support._util._common_types import JSONRPCResponseJSON, ToolException
from inspect_tool_support._util._validation import (
    pretty_validation_error,
    validate_params,
)

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)
P = ParamSpec("P")
R = TypeVar("R", str, int, BaseModel, None)


async def with_validated_rpc_method_params(
    cls: Type[BaseModelT],
    handler: Callable[[BaseModelT], Awaitable[str | int | BaseModel | None]],
    **params: object,
) -> str | BaseModel:
    """
    Validates RPC method parameters and handles the method execution.

    This function validates the provided parameters against the given Pydantic
    model class. If the validation is successful, it calls the provided handler
    with the validated parameters. The handler's result is then processed and
    returned accordingly.

    Args:
      cls (Type[BaseModelT]): The Pydantic model class used for validation.
      handler (Callable[[BaseModelT], Awaitable[str | int | BaseModel | None]]):
        The handler function to be called with the validated parameters. It can
        return a string, integer, BaseModel, or None.
      **params (object): The parameters to be validated.

    Returns:
      object: The result of the handler function, or an error message if
        validation or execution fails.
        Ideally, we'd type the return as Either[ErrorResult, SuccessResult], but
        `jsonrpcserver` doesn't export those public API types. D'oh!

    Raises:
      TypeError: If the handler returns an unexpected result type.
    """
    match validate_params(params, cls):
        case Failure(validation_error):
            return jsonrpcserver.Error(
                -32602, pretty_validation_error(validation_error)
            )
        case Success(validated_params):
            try:
                match await handler(validated_params):
                    case str(text):
                        return jsonrpcserver.Success(text)
                    case BaseModel() as model:
                        return jsonrpcserver.Success(model.model_dump())
                    case int(value):
                        return jsonrpcserver.Success(value)
                    case None:
                        return jsonrpcserver.Success(None)
                    case cant_happen:
                        raise TypeError(
                            f"Unexpected handler result type: {type(cant_happen)}"
                        )
            except ToolException as e:
                return jsonrpcserver.Error(code=-32099, message=e.message)
            except Exception as e:
                # Customize the jsonrpc error with the exception message and traceback
                # so that this info will be included in the eval log. This will still
                # fail the eval since it represents an inspect coding error.
                return jsonrpcserver.Error(
                    code=-32098, message=repr(e), data=traceback.format_exc()
                )
        case _:
            return jsonrpcserver.Error(
                -32602,
                pretty_validation_error(
                    ValidationError(f"Unexpected command: {params}")
                ),
            )


async def json_rpc_http_call(
    url: URL | str, request_json_str: str
) -> JSONRPCResponseJSON:
    return JSONRPCResponseJSON(
        (await _retrying_post(url, json.loads(request_json_str))).text
    )


async def _retrying_post(
    url: URL | str,
    body: object | None = None,
    max_retries: int = 3,
    total_timeout: int = 180,
) -> httpx.Response:
    @retry(
        wait=wait_exponential_jitter(),
        stop=(stop_after_attempt(max_retries) | stop_after_delay(total_timeout)),
        retry=retry_if_exception(_httpx_should_retry),
    )
    async def do_post() -> httpx.Response:
        async with AsyncClient() as client:
            return await client.post(url, json=body, timeout=30)

    return await do_post()


# TODO: cloned from inspect_ai repo code that is unavailable in the container
# fix this by copying that source file into the container
def _httpx_should_retry(ex: BaseException) -> bool:
    """Check whether an exception raised from httpx should be retried.

    Implements the strategy described here: https://cloud.google.com/storage/docs/retry-strategy

    Args:
      ex (BaseException): Exception to examine for retry behavior

    Returns:
      True if a retry should occur
    """
    # httpx status exception
    if isinstance(ex, HTTPStatusError):
        # request timeout
        if ex.response.status_code == 408:
            return True
        # lock timeout
        elif ex.response.status_code == 409:
            return True
        # rate limit
        elif ex.response.status_code == 429:
            return True
        # internal errors
        elif ex.response.status_code >= 500:
            return True
        else:
            return False

    # connection error
    elif _is_httpx_connection_error(ex):
        return True

    # don't retry
    else:
        return False


def _is_httpx_connection_error(ex: BaseException) -> bool:
    return isinstance(ex, ConnectTimeout | ConnectError | ConnectionError | ReadTimeout)


def validated_json_rpc_method(cls: Type[BaseModelT]):
    """
    A decorator that combines @method and with_validated_rpc_method_params.

    This decorator registers a function as a JSON-RPC method and handles
    parameter validation using the provided Pydantic model class.

    Args:
        cls (Type[BaseModelT]): The Pydantic model class used for parameter
          validation.

    Returns:
        Callable: A decorator that transforms the decorated function into a
          validated JSON-RPC method.

    Example:
        @validated_json_rpc_method(LaunchServerParams)
        async def mcp_launch_server(params: LaunchServerParams) -> int:
            session_id = next(id_generator)
            sessions[session_id] = await MCPServerSession.create(params.server_params)
            return session_id
    """

    def decorator(
        func: Callable[[BaseModelT], Awaitable[R]],
    ) -> Callable[..., Awaitable[object]]:
        async def wrapper(**params: object) -> object:
            return await with_validated_rpc_method_params(cls, func, **params)

        wrapper.__name__ = func.__name__
        return method(wrapper)

    return decorator
