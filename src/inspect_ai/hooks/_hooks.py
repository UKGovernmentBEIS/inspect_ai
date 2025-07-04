import asyncio
from dataclasses import dataclass
from logging import getLogger
from typing import Awaitable, Callable, Type, TypeVar, cast

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from inspect_ai._eval.eval import EvalLogs
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_find,
    registry_name,
)
from inspect_ai.hooks._legacy import override_api_key_legacy
from inspect_ai.log._log import EvalLog, EvalSampleSummary, EvalSpec
from inspect_ai.log._transcript import Event
from inspect_ai.model._model_output import ModelUsage

logger = getLogger(__name__)
# I'd naturally use asyncio.Queue (which supports synchronous putting), but given we're
# using anyio, we should be backend agnostic. I think its closest equivalent is
# anyio.create_memory_object_stream
# https://anyio.readthedocs.io/en/stable/streams.html#memory-object-streams
_batched_event_send: MemoryObjectSendStream["EventData"]


@dataclass(frozen=True)
class RunStart:
    """Run start hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    task_names: list[str]
    """The names of the tasks which will be used in the run."""


@dataclass(frozen=True)
class RunEnd:
    """Run end hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    logs: EvalLogs
    """All eval logs generated during the run. Can be headers only if the run was an
    `eval_set()`."""


@dataclass(frozen=True)
class TaskStart:
    """Task start hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    eval_id: str
    """The globally unique identifier for this task execution."""
    spec: EvalSpec
    """Specification of the task."""


@dataclass(frozen=True)
class TaskEnd:
    """Task end hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    eval_id: str
    """The globally unique identifier for the task execution."""
    log: EvalLog
    """The log generated for the task. Can be header only if the run was an
    `eval_set()`"""


@dataclass(frozen=True)
class SampleStart:
    """Sample start hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    eval_id: str
    """The globally unique identifier for the task execution."""
    sample_id: str
    """The globally unique identifier for the sample execution."""
    summary: EvalSampleSummary
    """Summary of the sample to be run."""


@dataclass(frozen=True)
class SampleEnd:
    """Sample end hook event data."""

    run_id: str
    """The globally unique identifier for the run."""
    eval_id: str
    """The globally unique identifier for the task execution."""
    sample_id: str
    """The globally unique identifier for the sample execution."""
    summary: EvalSampleSummary
    """Summary of the sample that has run."""


@dataclass(frozen=True)
class ModelUsageData:
    """Model usage hook event data."""

    model_name: str
    """The name of the model that was used."""
    usage: ModelUsage
    """The model usage metrics."""
    call_duration: float
    """The duration of the model call in seconds. If HTTP retries were made, this is the
    time taken for the successful call. This excludes retry waiting (e.g. exponential
    backoff) time."""


# TODO: For Jake's request of doing some analysis every N assistant messages, he'll
# presumably use the ModelEvent. This might not give him the information he needs to
# associate any analysis with a specific sample though.
@dataclass(frozen=True)
class EventData:
    """Transcript event hook event data."""

    event: Event
    """The event that was logged to the transcript."""


@dataclass(frozen=True)
class ApiKeyOverride:
    """Api key override hook event data."""

    env_var_name: str
    """The name of the environment var containing the API key (e.g. OPENAI_API_KEY)."""
    value: str
    """The original value of the environment variable."""


class Hooks:
    """Base class for hooks.

    Note that whenever hooks are called, they are wrapped in a try/except block to
    catch any exceptions that may occur. This is to ensure that a hook failure does not
    affect the overall execution of the eval. If a hook fails, a warning will be logged.
    """

    def enabled(self) -> bool:
        """Check if the hook should be enabled.

        Default implementation returns True.

        Hooks may wish to override this to e.g. check the presence of an environment
        variable or a configuration setting.

        Will be called frequently, so consider caching the result if the computation is
        expensive.
        """
        return True

    async def on_run_start(self, data: RunStart) -> None:
        """On run start.

        A "run" is a single invocation of `eval()` or `eval_retry()` which may contain
        many Tasks, each with many Samples and many epochs. Note that `eval_retry()`
        can be invoked multiple times within an `eval_set()`.

        Args:
           data: Run start data.
        """
        pass

    async def on_run_end(self, data: RunEnd) -> None:
        """On run end.

        Args:
           data: Run end data.
        """
        pass

    async def on_task_start(self, data: TaskStart) -> None:
        """On task start.

        Args:
           data: Task start data.
        """
        pass

    async def on_task_end(self, data: TaskEnd) -> None:
        """On task end.

        Args:
           data: Task end data.
        """
        pass

    async def on_sample_start(self, data: SampleStart) -> None:
        """On sample start.

        Called when a sample is about to be start. If the sample errors and retries,
        this will not be called again.

        If a sample is run for multiple epochs, this will be called once per epoch.

        Args:
           data: Sample start data.
        """
        pass

    async def on_sample_end(self, data: SampleEnd) -> None:
        """On sample end.

        Called when a sample has either completed successfully, or when a sample has
        errored and has no retries remaining.

        If a sample is run for multiple epochs, this will be called once per epoch.

        Args:
           data: Sample end data.
        """
        pass

    async def on_model_usage(self, data: ModelUsageData) -> None:
        """Called when a call to a model's generate() method completes successfully.

        Note that this is not called when Inspect's local cache is used and is a cache
        hit (i.e. if no external API call was made). Provider-side caching will result
        in this being called.

        Args:
           data: Model usage data.
        """
        pass

    # Note: This hook is simple and will be appropriate for some use cases. But we're
    # worried about users doing naive things here and blocking the main thread, then
    # blaming Inspect for being slow. Therefore, we want to encourage users to use
    # `on_event_batch()` where appropriate.
    def on_event(self, data: EventData) -> None:
        """Called when an event is logged to the transcript.

        This method is called synchronously as soon as an event is logged to the
        transcript. Therefore, this method may be called frequently. Since it is
        blocking, it should not perform any potentially long-running operations like web
        requests.

        For hooks that need to perform expensive operations or I/O, please use the
        `on_event_batch()` method instead.

        Args:
            data: Event data.
        """
        pass

    # TODO: Allow user to control throttling frequency e.g. with an `event_batch_period`
    # property on their Hooks class. We might always flush any events when we reach the
    # end of a sample. If we haven't logged any events in a throttling period, do we
    # emit an empty list?
    # Different subclasses of Hooks may have different throttling periods, so we may
    # need to have a background task per hook.
    # Should we use a background task to emit events in batches (a bit like
    # inspect_ai.util._background)? We need to decide what we want by making this method
    # async:
    # 1. Is it just so that we don't block the main thread and freeze the UI
    # 2. Or is it that we actually want to allow our eval to continue while the hook is
    #    being handled? In which case, this is more like a background task or fire &
    #    forget call.
    # If we're flushing this in a non-deterministic manner (e.g. periodically on in a
    # background task), we should document that the ordering of these events relative to
    # other hooks (e.g. on_sample_end) is not guaranteed.
    async def on_event_batch(self, events: list[EventData]) -> None:
        """Called periodically with a batch of logged transcript events.

        This method is called periodically with a batch of events. This is useful for
        hooks that need to:
        - Perform operations that are too expensive to do on every event.
        - Perform I/O operations that should not block the main thread.

        Args:
            events: List of event data objects.
        """
        pass

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        """Optionally override an API key.

        When overridden, this method may return a new API key value which will be used
        in place of the original one during the eval.

        Args:
            data: Api key override data.

        Returns:
            str | None: The new API key value to use, or None to use the original value.
        """
        return None


T = TypeVar("T", bound=Hooks)


def hooks(name: str, description: str) -> Callable[..., Type[T]]:
    """Decorator for registering a hook subscriber.

    Either decorate a subclass of `Hooks`, or a function which returns the type
    of a subclass of `Hooks`. This decorator will instantiate the hook class
    and store it in the registry.

    Args:
        name (str): Name of the subscriber (e.g. "audit logging").
        description (str): Short description of the hook (e.g. "Copies eval files to
            S3 bucket for auditing.").
    """

    def wrapper(hook_type: Type[T] | Callable[..., Type[T]]) -> Type[T]:
        # Resolve the hook type if it's a function.
        if not isinstance(hook_type, type):
            hook_type = hook_type()
        if not issubclass(hook_type, Hooks):
            raise TypeError(f"Hook must be a subclass of Hooks, got {hook_type}")

        # Instantiate an instance of the Hooks class.
        hook_instance = hook_type()
        hook_name = registry_name(hook_instance, name)
        registry_add(
            hook_instance,
            RegistryInfo(
                type="hooks", name=hook_name, metadata={"description": description}
            ),
        )
        return cast(Type[T], hook_type)

    return wrapper


async def emit_run_start(run_id: str, tasks: list[ResolvedTask]) -> None:
    data = RunStart(run_id=run_id, task_names=[task.task.name for task in tasks])
    await _emit_to_all(lambda hook: hook.on_run_start(data))

    # TODO: Start this background task in a more appropriate place (this could be called
    # multiple times under eval_set).
    global _batched_event_send
    _batched_event_send, batched_event_receive = anyio.create_memory_object_stream[
        EventData
    ](max_buffer_size=1024 * 10)
    # TODO: Ensure flushed before end of eval.
    asyncio.create_task(periodically_emit_event_batch(batched_event_receive))


async def emit_run_end(run_id: str, logs: EvalLogs) -> None:
    data = RunEnd(run_id=run_id, logs=logs)
    await _emit_to_all(lambda hook: hook.on_run_end(data))


async def emit_task_start(logger: TaskLogger) -> None:
    data = TaskStart(
        run_id=logger.eval.run_id, eval_id=logger.eval.eval_id, spec=logger.eval
    )
    await _emit_to_all(lambda hook: hook.on_task_start(data))


async def emit_task_end(logger: TaskLogger, log: EvalLog) -> None:
    data = TaskEnd(run_id=logger.eval.run_id, eval_id=logger.eval.eval_id, log=log)
    await _emit_to_all(lambda hook: hook.on_task_end(data))


async def emit_sample_start(
    run_id: str, eval_id: str, sample_id: str, summary: EvalSampleSummary
) -> None:
    data = SampleStart(
        run_id=run_id, eval_id=eval_id, sample_id=sample_id, summary=summary
    )
    await _emit_to_all(lambda hook: hook.on_sample_start(data))


async def emit_sample_end(
    run_id: str, eval_id: str, sample_id: str, summary: EvalSampleSummary
) -> None:
    data = SampleEnd(
        run_id=run_id, eval_id=eval_id, sample_id=sample_id, summary=summary
    )
    await _emit_to_all(lambda hook: hook.on_sample_end(data))


async def emit_model_usage(
    model_name: str, usage: ModelUsage, call_duration: float
) -> None:
    data = ModelUsageData(
        model_name=model_name, usage=usage, call_duration=call_duration
    )
    await _emit_to_all(lambda hook: hook.on_model_usage(data))


def emit_event(event: Event) -> None:
    # TODO: Also handle pushing this into a queue for batching, and periodically
    # flushing the queue to the hooks.
    data = EventData(event=event)
    for hook in get_all_hooks():
        if not hook.enabled():
            continue
        try:
            hook.on_event(data)
        except Exception as ex:
            logger.warning(
                f"Exception calling on_event on hook '{hook.__class__.__name__}': {ex}"
            )
    _batched_event_send.send_nowait(data)


async def periodically_emit_event_batch(
    receive: MemoryObjectReceiveStream[EventData],
) -> None:
    while True:
        await asyncio.sleep(1)
        # TODO: How to get all currently queued events?
        events = [await receive.receive()]
        if not events:
            continue
        for hook in get_all_hooks():
            if not hook.enabled():
                continue
            try:
                await hook.on_event_batch(events)
            except Exception as ex:
                logger.warning(
                    f"Exception calling on_event_batch on hook '{hook.__class__.__name__}': {ex}"
                )

    pass


def override_api_key(env_var_name: str, value: str) -> str | None:
    data = ApiKeyOverride(env_var_name=env_var_name, value=value)
    for hook in get_all_hooks():
        if not hook.enabled():
            continue
        try:
            overridden = hook.override_api_key(data)
            if overridden is not None:
                return overridden
        except Exception as ex:
            logger.warning(
                f"Exception calling override_api_key on hook '{hook.__class__.__name__}': {ex}"
            )
    # If none have been overridden, fall back to legacy behaviour.
    return override_api_key_legacy(env_var_name, value)


def get_all_hooks() -> list[Hooks]:
    """Get all registered hooks."""
    results = registry_find(lambda info: info.type == "hooks")
    return cast(list[Hooks], results)


async def _emit_to_all(callable: Callable[[Hooks], Awaitable[None]]) -> None:
    for hook in get_all_hooks():
        if not hook.enabled():
            continue
        try:
            await callable(hook)
        except Exception as ex:
            logger.warning(f"Exception calling hook '{hook.__class__.__name__}': {ex}")
