from claude import claude_code

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample


@task
def http_proxy_demo() -> Task:
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="Write a script that integrates the FutureModel API (https://api.futuremodel.ai/v1/chat/completions) and run it to generate a haiku about coding. The model name is 'futuremodel-1' and the API key is in the FUTUREMODEL_API_KEY environment variable.",
                )
            ]
        ),
        solver=claude_code(),
        sandbox="docker",
    )
