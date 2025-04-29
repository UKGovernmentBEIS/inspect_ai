from pydantic import BaseModel, ValidationError

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, ModelName, ResponseSchema, get_model
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
        scorer=score_json_color(),
        config=GenerateConfig(
            response_schema=ResponseSchema(name="color", json_schema=json_schema(Color))
        ),
    )


@scorer(metrics=[accuracy(), stderr()])
def score_json_color():
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


@task(vllm=True, sglang=True)
def rgb_color_regex():
    model = get_model()
    if ModelName(model).api == "vllm":
        guided_name = "guided_regex"
    elif ModelName(model).api == "sglang":
        guided_name = "regex"
    else:
        raise ValueError(f"Unsupported provider: {model.provider}")

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
        scorer=score_regex_color(),
        config=GenerateConfig(
            extra_body={
                guided_name: r"RGB: (\d{1,3}),(\d{1,3}),(\d{1,3})",
            },
        ),
    )


@task(vllm=True)
def rgb_color_choice():
    model = get_model()
    if ModelName(model).api != "vllm":
        raise ValueError("Choice is only supported for vLLM")

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
        scorer=score_regex_color(),
        config=GenerateConfig(
            extra_body={
                "guided_choice": ["RGB: 255,255,255", "RGB: 0,0,0"],
            },
        ),
    )


@task(vllm=True, sglang=True)
def rgb_color_grammar():
    grammar = """
root ::= rgb_color
rgb_color ::= "RGB: " rgb_values
rgb_values ::= number "," number "," number
number ::= digit | digit digit | digit digit digit
digit ::= "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9"
"""

    model = get_model()
    if ModelName(model).api == "vllm":
        guided_name = "guided_grammar"
    elif ModelName(model).api == "sglang":
        guided_name = "ebnf"
    else:
        raise ValueError(f"Unsupported provider: {model.provider}")

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
        scorer=score_regex_color(),
        config=GenerateConfig(
            extra_body={
                guided_name: grammar,
            },
        ),
    )


@scorer(metrics=[accuracy(), stderr()])
def score_regex_color():
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
