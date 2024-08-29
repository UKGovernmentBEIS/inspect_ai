from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai import Task
from inspect_ai._eval.evalset import schedule_pending_tasks
from inspect_ai._eval.loader import ResolvedTask
from inspect_ai.model import Model, get_model


@skip_if_no_openai
@skip_if_no_anthropic
def test_schedule_pending_tasks():
    task1 = Task(dataset=[], name="task1")
    task2 = Task(dataset=[], name="task2")
    task3 = Task(dataset=[], name="task3")
    openai = get_model("openai/gpt-4o")
    anthropic = get_model("anthropic/claude-3-haiku-20240307")
    mock = get_model("mockllm/model")

    def resolved_task(task: Task, model: Model):
        return ResolvedTask(
            task=task,
            task_args={},
            task_file=None,
            model=model,
            sandbox=None,
            sequence=1,
        )

    tasks = [
        resolved_task(task1, openai),
        resolved_task(task1, anthropic),
        resolved_task(task1, mock),
        resolved_task(task2, openai),
        resolved_task(task2, anthropic),
        resolved_task(task3, mock),
    ]

    schedule = schedule_pending_tasks(tasks)

    for models, tasks in schedule:
        print(f"models: {','.join([str(model) for model in models.models])}")
        print(f"tasks:  {','.join([task.name for task in tasks])}")
        print("")
