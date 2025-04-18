from textwrap import dedent
from typing import Any

from openai import BaseModel
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.model._openai import openai_chat_tools
from inspect_ai.scorer import includes
from inspect_ai.solver import bridge, solver
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.util._json import json_schema


def agent(tools: bool):
    async def run(sample: dict[str, Any]) -> dict[str, Any]:
        from openai import AsyncOpenAI

        assert sample["metadata"]["foo"] == "bar"

        class Message(BaseModel):
            text: str

        client = AsyncOpenAI()
        params = dict(
            model="inspect",
            messages=sample["input"],
            temperature=0.8,
            top_p=0.5,
            stop=["foo"],
            frequency_penalty=1,
            presence_penalty=1.5,
            seed=42,
            n=3,
            # logit bias types are out of sync w/ api docs
            logit_bias=dict([(42, 10), (43, -10)]),
            reasoning_effort="low",
            timeout=200,
            response_format=dict(
                type="json_schema",
                json_schema=dict(
                    name="message",
                    schema=json_schema(Message).model_dump(exclude_none=True),
                ),
            ),
        )
        if tools:
            params["tools"] = openai_chat_tools([testing_tool_info()])
            params["tool_choice"] = "auto"
        else:
            params["logprobs"] = True
            params["top_logprobs"] = 3

        completion = await client.chat.completions.create(**params)

        return {"output": completion.choices[0].message.content}

    return run


@task
def bridged_task(tools: bool):
    return Task(
        dataset=[
            Sample(
                input="Please print the word 'hello'?",
                target="hello",
                metadata={"foo": "bar"},
            )
        ],
        solver=bridge(agent(tools)),
        scorer=includes(),
    )


@task
def openai_api_task():
    # solver the calls the openai api directly (so should proceed unpatched)
    @solver
    def openai_api_solver():
        from openai import AsyncOpenAI

        async def solve(state, generate):
            client = AsyncOpenAI()
            await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": "Write a haiku about recursion in programming.",
                    },
                ],
            )
            return state

        return solve

    return Task(solver=openai_api_solver())


def eval_bridged_task(model: str, tools: bool) -> str:
    log = eval(bridged_task(tools), model=model)[0]
    assert log.status == "success"
    return log.model_dump_json(exclude_none=True, indent=2)


def check_openai_log_json(log_json: str, tools: bool):
    assert r'"model": "gpt-4o"' in log_json
    if tools:
        assert r'"name": "testing_tool"' in log_json
        assert r'"tool_choice": "auto"' in log_json
    assert r'"frequency_penalty": 1' in log_json
    assert dedent("""
    "stop": [
      "foo"
    ]
    """)
    assert dedent("""
    "logit_bias": {
      "42": 10,
      "43": -10
    },
    """)
    assert r'"presence_penalty": 1.5' in log_json
    assert r'"seed": 42' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert r'"n": 3' in log_json
    if not tools:
        assert r'"logprobs": true' in log_json
        assert r'"top_logprobs": 3' in log_json
    assert r'"response_schema"' in log_json
    assert r'"logprobs"' in log_json


@skip_if_no_openai
def test_bridged_agent():
    log_json = eval_bridged_task("openai/gpt-4o", tools=False)
    check_openai_log_json(log_json, tools=False)


@skip_if_no_openai
def test_bridged_agent_tools():
    log_json = eval_bridged_task("openai/gpt-4o", tools=True)
    check_openai_log_json(log_json, tools=True)


def check_anthropic_log_json(log_json: str):
    assert r'"model": "anthropic/claude-3-haiku-20240307"' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert dedent("""
    "stop_sequences": [
      "foo"
    ]
    """)


@skip_if_no_anthropic
@skip_if_no_openai
def test_anthropic_bridged_agent():
    log_json = eval_bridged_task("anthropic/claude-3-haiku-20240307", tools=False)
    check_anthropic_log_json(log_json)


@skip_if_no_openai
def test_bridged_agent_context():
    logs = eval(
        [bridged_task(tools=False), openai_api_task()],
        max_tasks=2,
        model="anthropic/claude-3-haiku-20240307",
    )
    for log in logs:
        assert log.status == "success"
        if log.eval.task == "bridged_task":
            log_json = log.model_dump_json(exclude_none=True, indent=2)
            check_anthropic_log_json(log_json)


def testing_tool_info() -> ToolInfo:
    return ToolInfo(
        name="testing_tool",
        description="This is a testing tool.",
        parameters=ToolParams(
            properties={
                "param1": ToolParam(
                    type="string",
                    description="This is parameter1",
                )
            },
            required=["param1"],
        ),
    )


if __name__ == "__main__":
    test_bridged_agent()
