import asyncio
import contextlib
from contextvars import ContextVar
from functools import wraps
from time import time
from typing import Any, AsyncGenerator, Optional, Type, cast

from openai import AsyncOpenAI
from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT
from openai.types.chat import ChatCompletion
from pydantic_core import to_json
from shortuuid import uuid

from inspect_ai.model._model import get_model
from inspect_ai.model._openai import chat_messages_from_openai, openai_chat_choices


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
    if not _patch_initialised:
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
            remaining_retries: Optional[int] = None,
        ) -> Any:
            # we have patched the underlying request method so now need to figure out when to
            # patch and when to stand down
            if (
                # enabled for this coroutine
                _patch_enabled.get()
                # completions request
                and options.url == "/chat/completions"
                # call to openai not another service (e.g. TogetherAI)
                and self.base_url == "https://api.openai.com/v1/"
            ):
                # check that we use "/" in model name (i.e. not a request for a standard
                # openai model)

                print(to_json(options, indent=2, fallback=lambda _: None).decode())
                json_data = cast(dict[str, Any], options.json_data)
                model = json_data["model"]
                if isinstance(model, str) and "/" in model:
                    # print(to_json(options, indent=2, fallback=lambda _: None).decode())
                    # pass
                    return await inspect_model_request(model, options)

            # otherwise just delegate
            return await original_request(
                self,
                cast_to,
                options,
                stream=stream,
                stream_cls=stream_cls,
                remaining_retries=remaining_retries,
            )

        setattr(AsyncAPIClient, "request", patched_request)


async def inspect_model_request(
    model: str, options: FinalRequestOptions
) -> ChatCompletion:
    # convert openai messages to inspect messages
    json_data = cast(dict[str, Any], options.json_data)
    messages = json_data["messages"]
    input = chat_messages_from_openai(messages)
    output = await get_model(model).generate(
        input=input,
        # TODO: tool calls
        # TODO: generation config
    )

    # inspect completion to openai completion
    return ChatCompletion(
        id=uuid(),
        created=int(time()),
        object="chat.completion",
        choices=openai_chat_choices(output.choices),
        model=model,
        # TODO: usage
        # TODO: logprobs inside openai_chat_choices
    )


if __name__ == "__main__":

    async def task1() -> None:
        async with openai_request_to_inspect_model():
            client = AsyncOpenAI()
            completion = await client.chat.completions.create(
                model="google/gemini-1.5-pro",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": "Write a haiku about recursion in programming.",
                    },
                ],
            )

        print(completion.model_dump_json(indent=2))

    async def task2() -> None:
        client = AsyncOpenAI()
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": "Write a haiku about recursion in programming.",
                },
            ],
        )

        print(completion.choices[0].message)

    async def main() -> None:
        await asyncio.gather(task1())

    asyncio.run(main())
