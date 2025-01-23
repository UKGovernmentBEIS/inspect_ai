from textwrap import dedent
from typing import Any

from openai import AsyncOpenAI
import pytest
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import bridge


async def agent(sample: dict[str, Any]) -> dict[str, Any]:
    client = AsyncOpenAI()
    completion = await client.chat.completions.create(
        messages=sample["messages"],
        model=sample["model"],
        temperature=0.8,
        top_p=0.5,
        stop=["foo"],
        frequency_penalty=1,
        presence_penalty=1.5,
        seed=42,
        n=3,
        logprobs=True,
        top_logprobs=3,
        parallel_tool_calls=True,
        reasoning_effort="low",
        timeout=200,
    )

    return {"output": completion.choices[0].message.content}


@task
def bridged_task():
    return Task(
        dataset=[Sample(input="Please print the word 'hello'?", target="hello")],
        solver=bridge(agent),
        scorer=includes(),
    )


def eval_bridged_task(model: str) -> str:
    log = eval(bridged_task(), model=model)[0]
    assert log.status == "success"
    return log.model_dump_json(exclude_none=True, indent=2)


def check_openai_log_json(log_json: str):
    assert r'"model": "gpt-4o-mini"' in log_json
    assert r'"frequency_penalty": 1' in log_json
    assert dedent("""
    "stop": [
      "foo"
    ]
    """)
    assert r'"presence_penalty": 1.5' in log_json
    assert r'"seed": 42' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert r'"n": 3' in log_json
    assert r'"logprobs": true' in log_json
    assert r'"top_logprobs": 3' in log_json
    assert dedent("""
    "logprobs": {
      "content": [
    """)


@skip_if_no_openai
def test_bridged_agent():
    log_json = eval_bridged_task("openai/gpt-4o-mini")
    check_openai_log_json(log_json)


@skip_if_no_anthropic
def test_anthropic_bridged_agent():
    log_json = eval_bridged_task("anthropic/claude-3-haiku-20240307")

    assert r'"model": "anthropic/claude-3-haiku-20240307"' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert dedent("""
    "stop_sequences": [
      "foo"
    ]
    """)


@skip_if_no_openai
def test_bridged_agent_context():
    pass
