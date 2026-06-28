import base64
from pathlib import Path

from inspect_ai import Task, TaskSource, eval
from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import ContentAudio, ContentImage, ContentVideo
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL, resolve_sample_attachments
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


def test_fixed_image_without_extension_uses_sniffed_format(tmp_path: Path) -> None:
    image = tmp_path / "input"
    image.write_bytes(b"\x89PNG\r\n\x1a\ntrusted-image")
    seen: list[str] = []

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(image_reference(state))
            return state

        return solve

    eval(
        Task(
            dataset=[Sample(id="sample", input=image_input(str(image)))],
            solver=record_input(),
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen[0].startswith("data:image/png;base64,")


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


def test_media_materialization_failure_is_retried() -> None:
    resolver_calls = [0]
    seen: list[str] = []

    async def resolver(uri: str) -> str:
        assert uri == "test://bucket/input.png"
        resolver_calls[0] += 1
        if resolver_calls[0] == 1:
            raise RuntimeError("transient media failure")
        return "data:image/png;base64,dHJ1c3RlZA=="

    @solver
    def record_input() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(image_reference(state))
            return state

        return solve

    with media_resolver("test", resolver):
        logs = eval(
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
            retry_on_error=1,
        )

    assert resolver_calls == [2]
    assert seen == ["data:image/png;base64,dHJ1c3RlZA=="]
    assert logs[0].status == "success"
    assert logs[0].samples is not None
    assert logs[0].samples[0].error_retries is not None
    assert len(logs[0].samples[0].error_retries) == 1


def test_media_materialization_failure_does_not_cancel_siblings(
    tmp_path: Path,
) -> None:
    seen: list[str | int] = []

    @solver
    def record_sample() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(state.sample_id)
            return state

        return solve

    logs = eval(
        Task(
            dataset=[
                Sample(
                    id="missing",
                    input=image_input(str(tmp_path / "missing.png")),
                ),
                Sample(id="ok", input="ok"),
            ],
            solver=record_sample(),
        ),
        model="mockllm/model",
        display="none",
        fail_on_error=False,
        log_images=False,
        max_samples=1,
    )

    assert logs[0].status == "success"
    assert seen == ["ok"]
    assert logs[0].samples is not None
    samples = {sample.id: sample for sample in logs[0].samples}
    assert samples["missing"].error is not None
    assert samples["ok"].error is None


def test_no_log_images_preserves_audio_and_video_formats(tmp_path: Path) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"trusted-audio")
    video = tmp_path / "input.mov"
    video.write_bytes(b"trusted-video")

    @solver
    def pass_through() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return state

        return solve

    logs = eval(
        Task(
            dataset=[
                Sample(
                    id="audio",
                    input=[
                        ChatMessageUser(
                            content=[ContentAudio(audio=str(audio), format="wav")]
                        )
                    ],
                ),
                Sample(
                    id="video",
                    input=[
                        ChatMessageUser(
                            content=[ContentVideo(video=str(video), format="mov")]
                        )
                    ],
                ),
            ],
            solver=pass_through(),
        ),
        model="mockllm/model",
        display="none",
        log_images=False,
    )

    assert logs[0].samples is not None
    logged = {sample.id: sample for sample in logs[0].samples}

    audio_input = logged["audio"].input
    assert not isinstance(audio_input, str)
    audio_content = audio_input[0].content
    assert isinstance(audio_content, list)
    logged_audio = audio_content[0]
    assert isinstance(logged_audio, ContentAudio)
    assert logged_audio.audio == BASE_64_DATA_REMOVED
    assert logged_audio.format == "wav"

    video_input = logged["video"].input
    assert not isinstance(video_input, str)
    video_content = video_input[0].content
    assert isinstance(video_content, list)
    logged_video = video_content[0]
    assert isinstance(logged_video, ContentVideo)
    assert logged_video.video == BASE_64_DATA_REMOVED
    assert logged_video.format == "mov"


def test_no_log_images_strips_media_from_retry_history(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    image_bytes = b"retry-media-must-not-be-logged"
    image.write_bytes(image_bytes)
    attempts = [0]

    @solver
    def retry_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await generate(state)
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("retry sample")
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input=image_input(str(image)))],
            solver=retry_once(),
        ),
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path / "logs"),
        log_format="json",
        log_images=False,
        log_realtime=False,
        retry_on_error=1,
    )

    assert attempts == [2]
    assert logs[0].samples is not None
    sample = logs[0].samples[0]
    assert sample.error_retries is not None
    assert len(sample.error_retries) == 1

    encoded_image = base64.b64encode(image_bytes).decode()
    retry_json = sample.error_retries[0].model_dump_json()
    assert encoded_image not in retry_json
    assert BASE_64_DATA_REMOVED in retry_json

    persisted_log = Path(logs[0].location).read_text()
    assert encoded_image not in persisted_log


def test_realtime_retry_preserves_changed_media_attachment(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    first_bytes = b"first-attempt-media"
    second_bytes = b"second-attempt-media"
    image.write_bytes(first_bytes)
    attempts = [0]

    @solver
    def retry_after_media_change() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts[0] += 1
            state = await generate(state)
            if attempts[0] == 1:
                image.write_bytes(second_bytes)
                raise RuntimeError("retry sample")
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input=image_input(str(image)))],
            solver=retry_after_media_change(),
        ),
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path / "logs"),
        log_images=True,
        log_realtime=True,
        retry_on_error=1,
    )

    assert attempts == [2]
    assert logs[0].samples is not None
    sample = resolve_sample_attachments(logs[0].samples[0], "full")
    assert sample.error_retries is not None
    assert len(sample.error_retries) == 1
    retry_events = sample.error_retries[0].events
    assert retry_events is not None
    retry_event = next(event for event in retry_events if isinstance(event, ModelEvent))
    retry_content = retry_event.input[0].content
    assert isinstance(retry_content, list)
    retry_image = retry_content[0]
    assert isinstance(retry_image, ContentImage)
    assert ATTACHMENT_PROTOCOL not in retry_image.image
    assert base64.b64decode(retry_image.image.split("base64,", 1)[1]) == first_bytes


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
