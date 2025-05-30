from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver._basic_agent import basic_agent
from inspect_ai.tool import bash, web_search

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
        sandbox=("docker", "./intervention/multi_tool/compose.yaml"),
        solver=basic_agent(
            tools=[
                bash(),
                web_search(
                    providers={
                        "openai": openai_options,
                        "anthropic": None,
                        "tavily": tavily_options,
                    },
                ),
            ]
        ),
        scorer=model_graded_qa(),
    )
