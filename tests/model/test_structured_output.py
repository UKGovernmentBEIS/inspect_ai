from pydantic import BaseModel, ValidationError
from test_helpers.utils import (
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_trio,
)

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, ResponseSchema
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate
from inspect_ai.util import json_schema


class Color(BaseModel):
    red: int
    green: int
    blue: int


@task
def rgb_color():
    return Task(
        dataset=[
            Sample(
                input="What is the RGB color for white?",
                target="255,255,255",
            )
        ],
        solver=generate(),
        scorer=score_color(),
        config=GenerateConfig(
            response_schema=ResponseSchema(name="color", json_schema=json_schema(Color))
        ),
    )


@scorer(metrics=[accuracy(), stderr()])
def score_color():
    async def score(state: TaskState, target: Target):
        try:
            color = Color.model_validate_json(state.output.completion)
            if f"{color.red},{color.green},{color.blue}" == target.text:
                value = CORRECT
            else:
                value = INCORRECT
            return Score(
                value=value,
                answer=state.output.completion,
            )
        except ValidationError as ex:
            return Score(
                value=INCORRECT,
                answer=state.output.completion,
                explanation=f"Error parsing response: {ex}",
            )

    return score


def check_structured_output(model):
    log = eval(rgb_color(), model=model)[0]
    assert log.status == "success"
    assert log.results.scores[0].metrics["accuracy"].value == 1


@skip_if_no_openai
def test_openai_structured_output():
    check_structured_output("openai/gpt-4o-mini")


@skip_if_no_google
@skip_if_trio
def test_google_structured_output():
    check_structured_output("google/gemini-2.0-flash")


@skip_if_no_mistral
def test_mistral_structured_output():
    check_structured_output("mistral/mistral-large-latest")
