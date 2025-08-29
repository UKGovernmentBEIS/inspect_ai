from textwrap import dedent
from typing import Any, cast

from anthropic import NOT_GIVEN as ANTHROPIC_NOT_GIVEN
from anthropic import AsyncAnthropic
from anthropic.types import ToolChoiceAnyParam
from openai import NOT_GIVEN, AsyncOpenAI, BaseModel
from openai.types.chat import ChatCompletion
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval, task
from inspect_ai._util.content import ContentToolUse
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai import (
    messages_to_openai,
    openai_chat_tools,
)
from inspect_ai.model._openai_responses import _tool_param_for_tool_info
from inspect_ai.model._prompt import user_prompt
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
    assert r'"model": "gpt-5"' in log_json
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
    if tools:
        assert r'"name": "testing_tool"' in log_json
        assert r'"tool_choice": "auto"' in log_json


@agent
def responses_agent(tools: bool) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge():
            client = AsyncOpenAI()

            responses_tools = (
                [
                    _tool_param_for_tool_info(
                        get_testing_tool_info(), "inspect", GenerateConfig()
                    )
                ]
                if tools
                else NOT_GIVEN
            )
            tool_choice = "auto" if tools else NOT_GIVEN

            response = await client.responses.create(
                model="inspect",
                input="Write a one-sentence bedtime story about a unicorn.",
                tools=responses_tools,
                tool_choice=tool_choice,  # type: ignore[call-overload]
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


@agent
def responses_web_search_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge():
            client = AsyncOpenAI()

            response = await client.responses.create(
                model="inspect",
                tools=[
                    {
                        "type": "web_search_preview",
                        "search_context_size": "low",
                    }
                ],
                input=user_prompt(state.messages).text,
            )

            message = ChatMessageAssistant(
                content=response.output_text, source="generate"
            )
            state.messages.append(message)
            state.output = ModelOutput.from_message(message)
            return state

    return execute


@agent
def anthropic_agent(tools: bool) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        def tools_param() -> Any:
            if tools:
                return [
                    {
                        "name": "get_weather",
                        "description": "Get the current weather in a given location",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city and state, e.g. San Francisco, CA",
                                }
                            },
                            "required": ["location"],
                        },
                    }
                ]
            else:
                return None

        async with agent_bridge(state) as bridge:
            client = AsyncAnthropic()

            await client.messages.create(
                model="inspect",
                max_tokens=4096,
                temperature=0.8,
                top_p=0.5,
                top_k=2,
                thinking={"type": "enabled", "budget_tokens": 2048}
                if not tools
                else ANTHROPIC_NOT_GIVEN,
                messages=[
                    {
                        "role": "user",
                        "content": user_prompt(state.messages).text,
                    }
                ],
                tools=tools_param(),
                tool_choice=ToolChoiceAnyParam(type="any")
                if tools
                else ANTHROPIC_NOT_GIVEN,
            )

            return bridge.state

    return execute


@agent
def anthropic_web_search_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            client = AsyncAnthropic()

            await client.messages.create(
                model="inspect",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": user_prompt(state.messages).text,
                    }
                ],
                tools=[
                    {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
                ],
            )

            return bridge.state

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
def web_search_task(agent: Agent):
    return Task(
        dataset=[
            Sample(
                input="What movie won best picture in 2025?",
                target="Anora",
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


@skip_if_no_openai
def test_bridged_agent_responses_tools():
    log_json = eval_bridged_task("openai/gpt-5", agent=responses_agent(True))
    check_openai_responses_log_json(log_json, tools=True)


@skip_if_no_openai
def test_bridged_web_search_tool_openai():
    log = eval(web_search_task(responses_web_search_agent()), model="openai/gpt-5")[0]
    log_json = log.model_dump_json(exclude_none=True, indent=2)
    assert '"search_context_size": "low"' in log_json
    check_web_search_tool_use(log, "web_search")


@skip_if_no_anthropic
def test_bridged_agent_anthropic():
    log_json = eval_bridged_task(
        "anthropic/claude-sonnet-4-20250514", agent=anthropic_agent(False)
    )
    check_anthropic_bridge_log_json(log_json, tools=False)


@skip_if_no_anthropic
def test_bridged_agent_anthropic_tools():
    log_json = eval_bridged_task(
        "anthropic/claude-sonnet-4-20250514", agent=anthropic_agent(True)
    )
    check_anthropic_bridge_log_json(log_json, tools=True)


@skip_if_no_anthropic
def test_bridged_web_search_tool_anthropic():
    log = eval(
        web_search_task(anthropic_web_search_agent()),
        model="anthropic/claude-sonnet-4-20250514",
    )[0]
    log_json = log.model_dump_json(exclude_none=True, indent=2)
    assert '"max_uses": 5' in log_json
    check_web_search_tool_use(log, "web_search")


@skip_if_no_anthropic
@skip_if_no_openai
def test_bridged_web_search_tool_openai_to_anthropic():
    log = eval(
        web_search_task(responses_web_search_agent()),
        model="anthropic/claude-sonnet-4-20250514",
    )[0]
    check_web_search_tool_use(log, "web_search")


@skip_if_no_anthropic
@skip_if_no_openai
def test_bridged_web_search_tool_anthropic_to_openai():
    log = eval(
        web_search_task(anthropic_web_search_agent()),
        model="openai/gpt-5",
    )[0]
    log_json = log.model_dump_json(exclude_none=True, indent=2)
    assert '"max_uses": 5' in log_json
    check_web_search_tool_use(log, "web_search")


def check_web_search_tool_use(log: EvalLog, tool_name: str):
    assert log.status == "success"
    assert log.samples
    model_event = next(
        (event for event in log.samples[0].events if event.event == "model")
    )
    assert model_event
    tool_use = next(
        (
            c
            for c in model_event.output.message.content
            if isinstance(c, ContentToolUse)
        ),
        None,
    )
    assert tool_use
    assert tool_use.tool_type == tool_name


def check_anthropic_log_json(log_json: str):
    assert r'"model": "anthropic/claude-sonnet-4-20250514"' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert dedent("""
    "stop_sequences": [
      "foo"
    ]
    """)


def check_anthropic_bridge_log_json(log_json: str, tools: bool):
    assert r'"model": "anthropic/claude-sonnet-4-20250514"' in log_json
    assert r'"max_tokens": 4096' in log_json
    assert r'"temperature": 0.8' in log_json
    assert r'"top_p": 0.5' in log_json
    assert r'"top_k": 2' in log_json
    if tools:
        assert r'"name": "get_weather"' in log_json
    else:
        assert r'"budget_tokens": 2048' in log_json


@skip_if_no_anthropic
@skip_if_no_openai
def test_anthropic_bridged_agent():
    log_json = eval_bridged_task(
        "anthropic/claude-sonnet-4-20250514", agent=completions_agent(False)
    )
    check_anthropic_log_json(log_json)


@skip_if_no_anthropic
@skip_if_no_openai
def test_bridged_agent_context():
    logs = eval(
        [bridged_task(agent=completions_agent(False)), openai_api_task()],
        max_tasks=2,
        model="anthropic/claude-sonnet-4-20250514",
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
