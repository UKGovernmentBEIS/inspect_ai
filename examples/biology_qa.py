from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver._basic_agent import basic_agent
from inspect_ai.tool import web_search

openai_options = {
    "search_context_size": "high",
    "user_location": {
        "type": "approximate",
        "country": "US",
        "city": "Boston",
    },
}

tavily_options = {"max_results": 5, "max_connections": 8}


@task
def biology_qa() -> Task:
    return Task(
        dataset=example_dataset(
            name="biology_qa",
            sample_fields=FieldSpec(input="question", target="answer"),
        ),
        solver=basic_agent(
            tools=[
                web_search(
                    providers={"openai": openai_options, "tavily": tavily_options},
                )
            ]
        ),
        scorer=model_graded_qa(),
    )
