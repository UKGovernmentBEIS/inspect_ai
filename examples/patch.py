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
    # TODO: handle 'no model' assuming their validation allows it?
    # TODO: some additional header we put in from our call to generate
    # TODO: checking that the get_model call succeeds
    # TODO: checking the baseURL if it comes in different (probably will from together)

    # do we need to forward this request to inspect_ai.model?
    if options.url == "/chat/completions":
        if options.json_data is not None:
            model = getattr(options.json_data, "model", "")
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


# async def inspect_model_request(
#     model: str, options: FinalRequestOptions
# ) -> ChatCompletion:
#     # TODO: openai messages to inspect messages
#     messages: list[ChatCompletionMessageParam] = getattr(options.json_data, "messages")

#     # TODO: Inspect completion to openai completion
#     return ChatCompletion()


setattr(AsyncAPIClient, "request", patched_request)


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
