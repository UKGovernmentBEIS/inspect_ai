"""Docker sandbox startup for samples a SampleSource adds to a running task.

With an empty seed the docker provider's ``task_init`` runs in the source's
feeder task rather than in the run's own context, so the cleanup state it
initialises must still be readable from the sample tasks.
"""

from contextvars import Context

from test_helpers.utils import skip_if_no_docker

from inspect_ai import SampleSource, Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate
from inspect_ai.util._sandbox.docker.cleanup import (
    auto_compose_files,
    project_record_auto_compose,
)
from inspect_ai.util._sandbox.docker.config import auto_compose_dir
from inspect_ai.util._sandbox.docker.util import ComposeProject


def test_auto_compose_recorded_without_cleanup_startup() -> None:
    # a context in which project_cleanup_startup() never ran (a sample task
    # whose task_init happened in a sibling task) can still record projects
    project = ComposeProject(
        name="inspect-test-project",
        config=str(auto_compose_dir() / "inspect-test-project.yaml"),
        sample_id=1,
        epoch=1,
        env=None,
    )
    assert project.config is not None

    def record() -> set[str]:
        project_record_auto_compose(project)
        return set(auto_compose_files())

    try:
        assert project.config in Context().run(record)
    finally:
        Context().run(lambda: auto_compose_files().discard(project.config))


class _OneAddedSample(SampleSource):
    def __init__(self) -> None:
        self._pending: list[Sample] = [Sample(input="Say hello.", target="hello")]

    def initial_samples(self) -> list[Sample]:
        return []

    async def next_samples(self) -> list[Sample] | None:
        pending, self._pending = self._pending, []
        return pending or None


@skip_if_no_docker
def test_sample_source_empty_seed_docker_sandbox() -> None:
    log = eval(
        Task(dataset=_OneAddedSample(), solver=generate(), sandbox="docker"),
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].error is None
