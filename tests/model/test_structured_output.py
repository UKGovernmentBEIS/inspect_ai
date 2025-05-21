from pydantic import BaseModel, ValidationError
from test_helpers.utils import (
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, ResponseSchema
from inspect_ai.model._model import get_model
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


def check_structured_output(task, model):
    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.results.scores[0].metrics["accuracy"].value == 1


def check_color_structured_output(model):
    check_structured_output(rgb_color(), model)


class Cell(BaseModel):
    paper_id: str
    column_name: str
    cell_value: str


class Table(BaseModel):
    cell_values: list[Cell]


@task
def nested_pydantic():
    return Task(
        dataset=[
            Sample(
                input="Please produce a Table object with three Cell objects "
                + "(you can use whatever values you want for paper_id, column_name, and cell_value)",
            )
        ],
        solver=generate(),
        scorer=score_table(),
        config=GenerateConfig(
            response_schema=ResponseSchema(name="table", json_schema=json_schema(Table))
        ),
    )


@scorer(metrics=[accuracy(), stderr()])
def score_table():
    async def score(state: TaskState, target: Target):
        try:
            table = Table.model_validate_json(state.output.completion)
            value = INCORRECT
            if len(table.cell_values) > 0:
                cell = table.cell_values[0]
                if cell.cell_value and cell.column_name and cell.paper_id:
                    value = CORRECT
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


def check_nested_pydantic_output(model):
    check_structured_output(nested_pydantic(), model)


@skip_if_no_openai
def test_openai_structured_output():
    check_color_structured_output("openai/gpt-4o-mini")
    check_nested_pydantic_output("openai/gpt-4o-mini")


@skip_if_no_openai
def test_openai_responses_structured_output():
    model = get_model("openai/gpt-4o-mini", responses_api=True)
    check_color_structured_output(model)
    check_nested_pydantic_output(model)


@skip_if_no_google
def test_google_structured_output():
    check_color_structured_output("google/gemini-2.0-flash")
    check_nested_pydantic_output("google/gemini-2.0-flash")


@skip_if_no_mistral
def test_mistral_structured_output():
    check_color_structured_output("mistral/mistral-large-latest")
    check_nested_pydantic_output("mistral/mistral-large-latest")
