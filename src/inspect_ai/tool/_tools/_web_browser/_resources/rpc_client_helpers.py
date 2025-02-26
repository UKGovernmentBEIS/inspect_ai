"""
This module provides helper functions and classes for making strongly typed RPC calls.

The module is designed to be generic and should not contain any use case specific logic.
It uses the `httpx` library for making HTTP requests, `jsonrpcclient` for handling JSON-RPC responses,
and `pydantic` for validating and parsing response data into Python objects.

Classes:
  RPCError: Custom exception for handling RPC errors.

Functions:
  typed_rpc_call: Makes a typed RPC call and returns the response as a Pydantic model.
"""

from typing import Generic, Mapping, Type, TypedDict, TypeVar

from httpx import (
    URL,
    Client,
    ConnectError,
    ConnectTimeout,
    HTTPStatusError,
    ReadTimeout,
    Response,
)
from jsonrpcclient import Error, Ok, parse, request
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)


class RPCError(RuntimeError):
    def __init__(self, *, code: int, message: str, data: object):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"RPCError {code}: {message}")

    def __str__(self):
        return f"RPCError {self.code}: {self.message} (data: {self.data})"


TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


def rpc_call(
    url: URL | str,
    method: str,
    params: dict[str, object] | None,
    response_class: Type[TBaseModel],
) -> TBaseModel:
    """
    Makes an RPC call to the specified URL with the given method and parameters, and returns the response as a parsed and validated instance of the specified response class.

    Args:
      url (URL | str): The URL to which the RPC call is made.
      method (str): The RPC method to be called.
      response_class (Type[TBaseModel]): The class to which the response should be deserialized.
      params (dict[str, object] | None, optional): The parameters to be sent with the RPC call. Defaults to None.

    Returns:
      TBaseModel: An instance of the response class containing the result of the RPC call.

    Raises:
      RPCError: If the RPC call returns an error response.
      RuntimeError: If an unexpected response is received.
    """
    match parse(_retrying_post(url, request(method, params)).json()):
        case Ok(ok_result):
            return response_class(**ok_result)
        case Error(code, message, data):
            raise RPCError(code=code, message=message, data=data)
        case _:
            raise RuntimeError("how did we get here")


def _retrying_post(url: URL | str, json: object | None = None) -> Response:
    max_retries = 3
    total_timeout = 180

    @retry(
        wait=wait_exponential_jitter(),
        stop=(stop_after_attempt(max_retries) | stop_after_delay(total_timeout)),
        retry=retry_if_exception(httpx_should_retry),
    )
    def do_post() -> Response:
        with Client() as client:
            return client.post(url, json=json, timeout=30)

    return do_post()


RPCArgsType = Type[Mapping[str, object]]


class RPCCallTypes(TypedDict, Generic[TBaseModel]):
    args_type: RPCArgsType
    response_class: Type[TBaseModel]


# TODO: cloned from inspect_ai repo code that is unavailable in the container
# fix this by copying that source file into the container
def httpx_should_retry(ex: BaseException) -> bool:
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
    elif is_httpx_connection_error(ex):
        return True

    # don't retry
    else:
        return False


def is_httpx_connection_error(ex: BaseException) -> bool:
    return isinstance(ex, ConnectTimeout | ConnectError | ConnectionError | ReadTimeout)
