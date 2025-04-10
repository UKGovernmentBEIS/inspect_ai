from agent import web_surfer_agent

from inspect_ai import Task, task
from inspect_ai.agent import bridge
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import model_graded_fact


@task
def research() -> Task:
    return Task(
        dataset=json_dataset("dataset.json"),
        solver=bridge(web_surfer_agent()),
        scorer=model_graded_fact(),
    )
