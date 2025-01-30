from textwrap import dedent
from typing import Any

from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import bridge, solver


async def agent(sample: dict[str, Any]) -> dict[str, Any]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    completion = await client.chat.completions.create(
        model="inspect",
        messages=sample["input"],
        temperature=0.8,
        top_p=0.5,
        stop=["foo"],
        frequency_penalty=1,
        presence_penalty=1.5,
        seed=42,
        n=3,
        logprobs=True,
        top_logprobs=3,
        # logit bias types are out of sync w/ api docs
        logit_bias=dict([(42, 10), (43, -10)]),  # type: ignore[call-overload]
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


def eval_bridged_task(model: str) -> str:
    log = eval(bridged_task(), model=model)[0]
    assert log.status == "success"
    return log.model_dump_json(exclude_none=True, indent=2)


def check_openai_log_json(log_json: str):
    assert r'"model": "gpt-4o"' in log_json
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
    assert r'"logprobs": true' in log_json
    assert r'"top_logprobs": 3' in log_json
    assert dedent("""
    "logprobs": {
      "content": [
    """)


@skip_if_no_openai
def test_bridged_agent():
    log_json = eval_bridged_task("openai/gpt-4o")
    check_openai_log_json(log_json)


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
    log_json = eval_bridged_task("anthropic/claude-3-haiku-20240307")
    check_anthropic_log_json(log_json)


@skip_if_no_openai
def test_bridged_agent_context():
    logs = eval(
        [bridged_task(), openai_api_task()],
        max_tasks=2,
        model="anthropic/claude-3-haiku-20240307",
    )
    for log in logs:
        assert log.status == "success"
        if log.eval.task == "bridged_task":
            log_json = log.model_dump_json(exclude_none=True, indent=2)
            check_anthropic_log_json(log_json)
