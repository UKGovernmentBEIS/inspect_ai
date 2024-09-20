import re
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from ._model import ModelOutput


@dataclass
class PromptTooLongError(Exception):
    message: str | None = None
    tokens_used: int | None = None
    model_limit_tokens: int | None = None


CANT_ASSIST = "Sorry, but I can't assist with that."


@dataclass
class LLMCannotAssistError(Exception):
    message: str | None = CANT_ASSIST


def handle_model_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await func(*args, **kwargs)
        if isinstance(result, tuple):
            model_output, model_call = result
        else:
            model_output = result
        raise_if_error(model_output)
        return result

    return wrapper


def raise_if_error(model_output: ModelOutput) -> None:
    if not model_output.choices or not model_output.choices[0].message.content:
        return

    msg = str(model_output.choices[0].message.content)

    error_checkers = [
        check_openai_too_long,
        check_gpt4_token_limit,
        check_claude_token_limit,
        check_openai_cannot_assist_with_that,
    ]

    for checker in error_checkers:
        checker(msg)


def check_openai_too_long(msg: str) -> None:
    if re.search(r"Invalid 'messages\[[0-9]*].content': string too long", msg):
        raise PromptTooLongError(message=msg)


def check_gpt4_token_limit(msg: str) -> None:
    match = re.search(
        r"This model's maximum context length is (\d+) tokens\. However, your messages resulted in (\d+) tokens",
        msg,
    )
    if match:
        raise PromptTooLongError(
            message=msg,
            tokens_used=int(match.group(2)),
            model_limit_tokens=int(match.group(1)),
        )


def check_claude_token_limit(msg: str) -> None:
    match = re.search(r"prompt is too long: (\d+) tokens > (\d+) maximum", msg)
    if match:
        raise PromptTooLongError(
            message=msg,
            tokens_used=int(match.group(1)),
            model_limit_tokens=int(match.group(2)),
        )


def check_openai_cannot_assist_with_that(msg: str) -> None:
    match = re.search(CANT_ASSIST, msg)
    if match:
        raise LLMCannotAssistError(message=msg)
