from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import web_search


@task
def biology_qa() -> Task:
    return Task(
        dataset=example_dataset(
            name="biology_qa",
            sample_fields=FieldSpec(input="question", target="answer"),
        ),
        solver=[use_tools(web_search()), generate()],
        scorer=model_graded_qa(),
    )
