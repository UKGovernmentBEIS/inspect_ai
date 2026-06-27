import base64
from pathlib import Path

from inspect_ai import Task, TaskSource, eval
from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import ContentAudio, ContentImage
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    ModelOutput,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import materialize_media, media_resolver


def image_input(reference: str) -> list[ChatMessage]:
    return [ChatMessageUser(content=[ContentImage(image=reference)])]


def audio_input(reference: str) -> list[ChatMessage]:
    return [ChatMessageUser(content=[ContentAudio(audio=reference, format="mp3")])]


def image_reference(state: TaskState) -> str:
    assert not isinstance(state.input, str)
    content = state.input[0].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    return image.image


def audio_reference(state: TaskState) -> str:
    assert not isinstance(state.input, str)
    content = state.input[0].content
    assert isinstance(content, list)
    audio = content[0]
    assert isinstance(audio, ContentAudio)
    return audio.audio


def logged_image_reference(sample: EvalSample) -> str:
    input = sample.input
    assert not isinstance(input, str)
    content = input[0].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    return image.image


def logged_message_image_reference(sample: EvalSample) -> str:
    content = sample.messages[-1].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    return image.image


def test_fixed_input_materializes_independently_of_log_images(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    image.write_bytes(b"trusted-input")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(image_reference(state))
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input=image_input(str(image)))],
            solver=record_input(),
        ),
        model="mockllm/model",
        display="none",
        log_images=False,
    )

    assert base64.b64decode(seen[0].split("base64,", 1)[1]) == b"trusted-input"
    assert logs[0].samples is not None
    assert logged_image_reference(logs[0].samples[0]) == BASE_64_DATA_REMOVED


def test_fixed_input_uses_configured_media_resolver() -> None:
    seen: list[str] = []

    async def resolver(uri: str) -> str:
        assert uri == "test://bucket/input.png"
        return "data:image/png;base64,dHJ1c3RlZA=="

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(image_reference(state))
            return state

        return solve

    with media_resolver("test", resolver):
        eval(
            Task(
                dataset=[
                    Sample(
                        id="sample",
                        input=image_input("test://bucket/input.png"),
                    )
                ],
                solver=record_input(),
            ),
            model="mockllm/model",
            display="none",
            log_images=False,
        )

    assert seen == ["data:image/png;base64,dHJ1c3RlZA=="]


def test_fixed_audio_without_extension_uses_declared_format(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "input"
    audio.write_bytes(b"trusted-audio")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(audio_reference(state))
            return state

        return solve

    eval(
        Task(
            dataset=[Sample(id="sample", input=audio_input(str(audio)))],
            solver=record_input(),
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen[0].startswith("data:audio/mpeg;base64,")
    assert base64.b64decode(seen[0].split("base64,", 1)[1]) == b"trusted-audio"


def test_pending_sample_replacement_does_not_inherit_authority(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "seed":
                state.output = ModelOutput.from_content(str(state.model), str(secret))
            else:
                seen.append(image_reference(state))
            return state

        return solve

    task = Task(
        dataset=[
            Sample(id="seed", input="seed"),
            Sample(
                id="pending",
                input=image_input("data:image/png;base64,AA=="),
            ),
        ],
        solver=record_input(),
    )

    async def on_sample(sample: EvalSample, owning_task: Task) -> None:
        if sample.id == "seed":
            pending = owning_task.dataset[1]
            assert not isinstance(pending.input, str)
            content = pending.input[0].content
            assert isinstance(content, list)
            image = content[0]
            assert isinstance(image, ContentImage)
            image.image = sample.output.completion

    logs = eval(
        TaskSource.from_tasks([task], sample_complete=on_sample),
        model="mockllm/model",
        display="none",
        max_samples=1,
    )

    assert seen == [str(secret)]
    pending = next(
        sample
        for log in logs
        for sample in (log.samples or [])
        if sample.id == "pending"
    )
    assert logged_message_image_reference(pending) == str(secret)


def test_task_source_followup_input_is_inline_only(tmp_path: Path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "seed":
                state.output = ModelOutput.from_content(str(state.model), str(secret))
            else:
                seen.append(image_reference(state))
            return state

        return solve

    seed = Task(
        dataset=[Sample(id="seed", input="seed")],
        solver=record_input(),
        name="seed",
    )

    async def on_task(log: EvalLog) -> list[Task] | None:
        if log.eval.task != "seed":
            return None
        samples = log.samples
        assert samples is not None
        reference = samples[0].output.completion
        return [
            Task(
                dataset=[Sample(id="followup", input=image_input(reference))],
                solver=record_input(),
                name="followup",
            )
        ]

    logs = eval(
        TaskSource.from_tasks([seed], task_complete=on_task),
        model="mockllm/model",
        display="none",
    )

    assert seen == [str(secret)]
    followup = next(
        sample
        for log in logs
        for sample in (log.samples or [])
        if sample.id == "followup"
    )
    assert logged_message_image_reference(followup) == str(secret)


def test_explicitly_materialized_followup_input_is_inline(tmp_path: Path) -> None:
    image = tmp_path / "trusted.png"
    image.write_bytes(b"explicitly-authorized")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(image_reference(state))
            return state

        return solve

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(dataset=[Sample(id="seed", input="seed")], name="seed")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task != "seed":
                return None
            data_uri = await materialize_media(str(image))
            return [
                Task(
                    dataset=[Sample(id="followup", input=image_input(data_uri))],
                    solver=record_input(),
                    name="followup",
                )
            ]

    eval(Source(), model="mockllm/model", display="none")

    assert base64.b64decode(seen[0].split("base64,", 1)[1]) == b"explicitly-authorized"


def test_runtime_media_reference_is_preserved_without_finalizer_io(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")

    @solver
    def append_media() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.messages.append(
                ChatMessageAssistant(
                    content=[ContentImage(image=str(secret))],
                    source="generate",
                )
            )
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input="seed")],
            solver=append_media(),
        ),
        model="mockllm/model",
        display="none",
    )

    assert logs[0].samples is not None
    assert logged_message_image_reference(logs[0].samples[0]) == str(secret)


def test_runtime_media_reference_does_not_invoke_resolver() -> None:
    resolver_calls: list[str] = []

    async def resolver(uri: str) -> str:
        resolver_calls.append(uri)
        return "data:image/png;base64,dW5leHBlY3RlZA=="

    @solver
    def append_media() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.messages.append(
                ChatMessageAssistant(
                    content=[ContentImage(image="test://runtime/image.png")],
                    source="generate",
                )
            )
            return state

        return solve

    with media_resolver("test", resolver):
        logs = eval(
            Task(
                dataset=[Sample(id="sample", input="seed")],
                solver=append_media(),
            ),
            model="mockllm/model",
            display="none",
        )

    assert resolver_calls == []
    assert logs[0].samples is not None
    assert (
        logged_message_image_reference(logs[0].samples[0]) == "test://runtime/image.png"
    )
