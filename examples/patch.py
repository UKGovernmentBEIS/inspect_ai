import asyncio
from typing import Any, Optional, Type

from openai import AsyncOpenAI
from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT

original_request = getattr(AsyncAPIClient, "request")


async def patched_request(
    self,
    cast_to: Type[ResponseT],
    options: FinalRequestOptions,
    *,
    stream: bool = False,
    stream_cls: type[_AsyncStreamT] | None = None,
    remaining_retries: Optional[int] = None,
) -> Any:
    # TODO: consider co-routine based patching?

    # we have patched the underlying request method so now need to figure out when to
    # patch and when to stand down
    if (
        # completions request
        options.url == "/chat/completions"
        # call to openai not another service (e.g. TogetherAI)
        and self.base_url == "https://api.openai.com/v1"
    ):
        # check that we use "/" in model name (i.e. not a request for a standard
        # openai model)
        model = getattr(options.json_data or {}, "model", "")
        if "/" in model:
            pass
            # return await inspect_model_request(model, options)

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


# async def inspect_model_request(
#     model: str, options: FinalRequestOptions
# ) -> ChatCompletion:
#     # TODO: openai messages to inspect messages
#     messages: list[ChatCompletionMessageParam] = getattr(options.json_data, "messages")

#     # TODO: Inspect completion to openai completion
#     return ChatCompletion()


async def main():
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


asyncio.run(main())
