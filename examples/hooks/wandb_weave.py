import os
from contextlib import _GeneratorContextManager

import weave
from pydantic_core import to_jsonable_python
from weave import ThreadContext
from weave.trace.settings import UserSettings
from weave.trace.weave_client import WeaveClient

from inspect_ai.hooks import (
    Hooks,
    RunEnd,
    RunStart,
    SampleEnd,
    SampleStart,
    TaskEnd,
    TaskStart,
    hooks,
)
from inspect_ai.log import EvalSpec


@hooks(name="weave_hooks", description="Weights & Biases Weave")
class WeaveHooks(Hooks):
    """Weights & Biases Weave Hooks.

    Weave hooks will capture LLM generations and a summary of each sample
    (inputs, outputs, etc.), creating a Weave Thread for each sample.

    To enable the hooks, import this module and ensure that the
    WANDB_PROJECT_ID and WANDB_API_KEY environment variables are defined.

    """

    def __init__(self) -> None:
        # weave client (will be created/destroyed on run start/end)
        self._client: WeaveClient | None = None

        # track in flight tasks
        self._tasks: dict[str, EvalSpec] = {}

        # track in flight weave threads (one for each sample)
        self._threads: dict[
            str, _GeneratorContextManager[ThreadContext, None, None]
        ] = {}

    def enabled(self) -> bool:
        # opt-in to hooks with WANDB environment variables
        return (
            os.getenv("WANDB_PROJECT_ID", None) is not None
            and os.getenv("WANDB_API_KEY", None) is not None
        )

    async def on_run_start(self, data: RunStart) -> None:
        # create weave client
        self._client = weave.init(
            project_name=os.getenv("WANDB_PROJECT_ID", ""),
            settings=UserSettings(print_call_link=False),
        )

    async def on_run_end(self, data: RunEnd) -> None:
        # tear down weave client
        assert self._client
        self._client.finish()
        self._client = None

    async def on_task_start(self, data: TaskStart) -> None:
        # track running tasks (for sample metadata)
        self._tasks[data.eval_id] = data.spec

    async def on_task_end(self, data: TaskEnd) -> None:
        # stop tracking task
        self._tasks.pop(data.eval_id, None)

    async def on_sample_start(self, data: SampleStart) -> None:
        assert self._client

        # create legible thread_id (note: slashes not allowed)
        eval_spec = self._tasks.get(data.eval_id)
        task_name = eval_spec.task if eval_spec else "task"
        dataset_id = data.summary.id
        epoch = data.summary.epoch
        model = f"-{eval_spec.model}" if eval_spec else ""
        thread_id = f"{task_name}-{dataset_id}[{epoch}]{model}-{data.sample_id}"
        thread_id = thread_id.replace("/", "-")

        # create thread and track it for cleanup
        thread_ctx = weave.thread(thread_id=thread_id)
        thread_ctx.__enter__()
        self._threads[data.sample_id] = thread_ctx

    async def on_sample_end(self, data: SampleEnd) -> None:
        assert self._client

        try:
            # sample complete
            eval_spec = self._tasks.get(data.eval_id)
            call = self._client.create_call(
                "sample_complete",
                inputs={
                    "id": data.sample.id,
                    "epoch": data.sample.epoch,
                    "model": eval_spec.model if eval_spec else None,
                    "input": to_jsonable_python(data.sample.input),
                    "metadata": data.sample.metadata,
                },
                use_stack=False,
            )
            self._client.finish_call(
                call,
                output={
                    "output": to_jsonable_python(data.sample.output),
                    "scores": to_jsonable_python(data.sample.scores),
                    "error": data.sample.error,
                    "total_time": data.sample.total_time,
                    "working_time": data.sample.working_time,
                },
            )
        finally:
            # exit thread
            thread_ctx = self._threads.pop(data.sample_id)
            thread_ctx.__exit__(None, None, None)
