from datetime import datetime, timedelta, timezone

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate, use_tools
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

gemini_options = {
    "time_range_filter": {
        "start_time": datetime.now(timezone.utc).replace(microsecond=0)
        - timedelta(days=365),
        "end_time": datetime.now(timezone.utc).replace(microsecond=0),
    }
}


@task
def biology_qa() -> Task:
    return Task(
        dataset=example_dataset(
            name="biology_qa",
            sample_fields=FieldSpec(input="question", target="answer"),
        ),
        solver=[
            use_tools(
                web_search(
                    providers={
                        "grok": True,
                        "openai": openai_options,
                        "anthropic": True,
                        "tavily": tavily_options,
                        "gemini": gemini_options,
                    },
                )
            ),
            generate(),
        ],
        scorer=model_graded_qa(),
    )
