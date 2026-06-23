from pathlib import Path

from agent import web_research_agent

from inspect_ai import Task, task
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import model_graded_fact

DATASET = Path(__file__).resolve().parent.parent / "dataset.json"


@task
def research() -> Task:
    return Task(
        dataset=json_dataset(DATASET.as_posix()),
        solver=web_research_agent(),
        scorer=model_graded_fact(),
    )
