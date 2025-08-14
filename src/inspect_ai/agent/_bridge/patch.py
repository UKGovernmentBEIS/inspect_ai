import contextlib
import re
from contextvars import ContextVar
from functools import wraps
from typing import Any, AsyncGenerator, Type, cast

from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT

from inspect_ai.agent._bridge.request import inspect_model_request


@contextlib.asynccontextmanager
async def openai_request_to_inspect_model() -> AsyncGenerator[None, None]:
    # ensure one time init
    init_openai_request_patch()

    # set the patch enabled for this context and child coroutines
    token = _patch_enabled.set(True)
    try:
        yield
    finally:
        _patch_enabled.reset(token)


_patch_initialised: bool = False

_patch_enabled: ContextVar[bool] = ContextVar(
    "openai_request_patch_enabled", default=False
)


def init_openai_request_patch() -> None:
    global _patch_initialised
    if _patch_initialised:
        return

    # get reference to original method
    original_request = getattr(AsyncAPIClient, "request")
    if original_request is None:
        raise RuntimeError("Couldn't find 'request' method on AsyncAPIClient")

    @wraps(original_request)
    async def patched_request(
        self: AsyncAPIClient,
        cast_to: Type[ResponseT],
        options: FinalRequestOptions,
        *,
        stream: bool = False,
        stream_cls: type[_AsyncStreamT] | None = None,
    ) -> Any:
        # we have patched the underlying request method so now need to figure out when to
        # patch and when to stand down
        if (
            # enabled for this coroutine
            _patch_enabled.get()
            # completions request
            and options.url == "/chat/completions"
        ):
            # must also be an explicit request for an inspect model
            json_data = cast(dict[str, Any], options.json_data)
            model_name = str(json_data["model"])
            if re.match(r"^inspect/?", model_name):
                return await inspect_model_request(json_data)

        # otherwise just delegate
        return await original_request(
            self,
            cast_to,
            options,
            stream=stream,
            stream_cls=stream_cls,
        )

    setattr(AsyncAPIClient, "request", patched_request)
    _patch_initialised = True
