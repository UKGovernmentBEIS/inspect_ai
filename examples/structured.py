from pydantic import BaseModel, ValidationError

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, GuidedDecodingConfig, ResponseSchema
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
            ),
            Sample(
                input="What is the RGB color for black?",
                target="0,0,0",
            ),
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


@task(vllm=True)
def rgb_color_regex():
    return Task(
        dataset=[
            Sample(
                input="What is the RGB color for white?",
                target="255,255,255",
            ),
            Sample(
                input="What is the RGB color for black?",
                target="0,0,0",
            ),
        ],
        solver=generate(),
        scorer=score_regex(),
        config=GenerateConfig(
            guided_decoding=GuidedDecodingConfig(
                regex=r"RGB: (\d{1,3}),(\d{1,3}),(\d{1,3})"
            )
        ),
    )


@scorer(metrics=[accuracy(), stderr()])
def score_regex():
    async def score(state: TaskState, target: Target):
        try:
            # Check if the output matches the expected RGB format
            import re

            pattern = r"RGB: (\d{1,3}),(\d{1,3}),(\d{1,3})"
            match = re.search(pattern, state.output.completion)

            if match:
                # Extract the RGB values
                rgb_output = match.group(0)[len("RGB: ") :]
                if rgb_output == target.text:
                    value = CORRECT
                else:
                    value = INCORRECT
                return Score(
                    value=value,
                    answer=rgb_output,
                )
            else:
                return Score(
                    value=INCORRECT,
                    answer=state.output.completion,
                    explanation="Output does not match RGB format (r,g,b)",
                )
        except Exception as ex:
            return Score(
                value=INCORRECT,
                answer=state.output.completion,
                explanation=f"Error processing response: {ex}",
            )

    return score
