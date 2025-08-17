from textwrap import dedent
from typing import Any, cast

from openai import AsyncOpenAI, BaseModel
from openai.types.chat import ChatCompletion
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval, task
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai import (
    messages_to_openai,
    openai_chat_tools,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import solver
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.util._json import json_schema


@agent
def completions_agent(tools: bool) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge():

            class Message(BaseModel):
                text: str

            client = AsyncOpenAI()
            params: dict[str, Any] = dict(
                model="inspect",
                messages=await messages_to_openai(state.messages),
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
                params["tools"] = openai_chat_tools([get_testing_tool_info()])
                params["tool_choice"] = "auto"
            else:
                params["logprobs"] = True
                params["top_logprobs"] = 3

            completion = cast(
                ChatCompletion, await client.chat.completions.create(**params)
            )

            message = ChatMessageAssistant(
                content=completion.choices[0].message.content or "", source="generate"
            )
            state.messages.append(message)
            state.output = ModelOutput.from_message(message)
            return state

    return execute


def check_openai_responses_log_json(log_json: str, tools: bool):
    # assert r'"model": "gpt-5"' in log_json
    assert r'"You are a dope model."' in log_json
    assert r'"max_output_tokens": 2048' in log_json
    assert r'"parallel_tool_calls": true' in log_json
    assert r'"effort": "low"' in log_json
    assert r'"summary": "auto"' in log_json
    assert r'"service_tier": "default"' in log_json
    assert r'"max_tool_calls": 5' in log_json
    assert r'"foo": "bar"' in log_json
    assert r'"prompt_cache_key": "42"' in log_json
    assert r'"safety_identifier": "42"' in log_json
    assert r'"truncation": "auto"' in log_json


@agent
def responses_agent(tools: bool) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge():
            client = AsyncOpenAI()

            response = await client.responses.create(
                model="inspect",
                input="Write a one-sentence bedtime story about a unicorn.",
                instructions="You are a dope model.",
                max_output_tokens=2048,
                parallel_tool_calls=True,
                reasoning={"effort": "low", "summary": "auto"},
                service_tier="default",
                max_tool_calls=5,
                metadata={"foo": "bar"},
                prompt_cache_key="42",
                safety_identifier="42",
                truncation="auto",
            )

            message = ChatMessageAssistant(
                content=response.output_text, source="generate"
            )
            state.messages.append(message)
            state.output = ModelOutput.from_message(message)
            return state

    return execute


@task
def bridged_task(agent: Agent):
    return Task(
        dataset=[
            Sample(
                input="Please print the word 'hello'?",
                target="hello",
            )
        ],
        solver=agent,
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


def eval_bridged_task(model: str, agent: Agent) -> str:
    log = eval(bridged_task(agent), model=model)[0]
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
def test_bridged_agent_completions():
    log_json = eval_bridged_task("openai/gpt-4o", agent=completions_agent(False))
    check_openai_log_json(log_json, tools=False)


@skip_if_no_openai
def test_bridged_agent_completions_tools():
    log_json = eval_bridged_task("openai/gpt-4o", agent=completions_agent(True))
    check_openai_log_json(log_json, tools=True)


@skip_if_no_openai
def test_bridged_agent_responses():
    log_json = eval_bridged_task("openai/gpt-5", agent=responses_agent(False))
    check_openai_responses_log_json(log_json, tools=False)


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
    log_json = eval_bridged_task(
        "anthropic/claude-3-haiku-20240307", agent=completions_agent(False)
    )
    check_anthropic_log_json(log_json)


@skip_if_no_anthropic
@skip_if_no_openai
def test_bridged_agent_context():
    logs = eval(
        [bridged_task(agent=completions_agent(False)), openai_api_task()],
        max_tasks=2,
        model="anthropic/claude-3-haiku-20240307",
    )
    for log in logs:
        assert log.status == "success"
        if log.eval.task == "bridged_task":
            log_json = log.model_dump_json(exclude_none=True, indent=2)
            check_anthropic_log_json(log_json)


def get_testing_tool_info() -> ToolInfo:
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
    test_bridged_agent_completions()
