import asyncio
from typing import Optional, Type

from openai import AsyncOpenAI
from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT
from pydantic_core import to_json

original_request = getattr(AsyncAPIClient, "request")


async def patched_request(
    self,
    cast_to: Type[ResponseT],
    options: FinalRequestOptions,
    *,
    stream: bool = False,
    stream_cls: type[_AsyncStreamT] | None = None,
    remaining_retries: Optional[int] = None,
) -> ResponseT:
    print("CALLED PATCHED REQUEST")
    print(to_json(options, indent=2, fallback=lambda _: None).decode())
    response = await original_request(
        self,
        cast_to,
        options,
        stream=stream,
        stream_cls=stream_cls,
        remaining_retries=remaining_retries,
    )

    print(response)
    print(type(response))
    # openai.types.chat.chat_completion.ChatCompletion
    # print(to_json(response, indent=2, fallback=lambda _: None))
    return response


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
