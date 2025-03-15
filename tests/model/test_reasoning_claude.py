import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample
from inspect_ai.model._generate_config import GenerateConfig

from .test_reasoning_content import check_reasoning_content


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_reasoning_claude():
    await check_reasoning_content("anthropic/claude-3-7-sonnet-20250219")


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_reasoning_claude_ignore_unsupported():
    await check_reasoning_content(
        "anthropic/claude-3-7-sonnet-20250219",
        config=GenerateConfig(temperature=0.9, top_p=3, top_k=3),
    )


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_reasoning_claude_force_history():
    await check_reasoning_content(
        "anthropic/claude-3-7-sonnet-20250219",
        config=GenerateConfig(reasoning_history="none"),
    )


def check_max_tokens(max_tokens: int | None, reasoning_tokens: int, check_tokens: int):
    task = Task(dataset=[Sample(input="Please say 'hello, world'")])
    log = eval(
        task,
        log_format="json",
        model="anthropic/claude-3-7-sonnet-20250219",
        max_tokens=max_tokens,
        reasoning_tokens=reasoning_tokens,
    )[0]
    log_json = log.model_dump_json(indent=2)
    assert f'"max_tokens": {check_tokens}' in log_json
    assert log.status == "success"


DEFAULT_MAX_TOKENS = 4096


@skip_if_no_anthropic
def test_reasoning_claude_max_tokens():
    check_max_tokens(None, 1024, DEFAULT_MAX_TOKENS + 1024)
    check_max_tokens(5000, 2000, 5000)
    check_max_tokens(None, 8096, DEFAULT_MAX_TOKENS + 8096)


@skip_if_no_anthropic
def test_reasoning_claude_streaming():
    reasoning_tokens = 32 * 1024
    check_max_tokens(None, reasoning_tokens, DEFAULT_MAX_TOKENS + reasoning_tokens)


@skip_if_no_anthropic
def test_reasoning_claude_redacted():
    task = Task(
        dataset=[
            Sample(
                input="ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
            )
        ]
    )
    log = eval(
        task,
        model="anthropic/claude-3-7-sonnet-20250219",
        reasoning_tokens=1024,
    )[0]

    assert log.samples
    output = log.samples[0].output
    content = output.choices[0].message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)
    assert content[0].redacted


@skip_if_no_anthropic
def test_reasoning_claude_token_count():
    task = Task(dataset=[Sample(input="Please say 'hello, world'")])
    log = eval(
        task,
        model="anthropic/claude-3-7-sonnet-20250219",
        reasoning_tokens=1024,
    )[0]

    assert log.samples
    output = log.samples[0].output
    assert output.usage.reasoning_tokens > 0
