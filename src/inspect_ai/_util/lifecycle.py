from dataclasses import dataclass
from logging import getLogger
from typing import Awaitable, Callable, Type, TypeVar, cast

from inspect_ai._eval.eval import EvalLogs
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_find,
    registry_name,
)
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.model._model_output import ModelUsage

logger = getLogger(__name__)


@dataclass(frozen=True)
class EvalStartEvent:
    run_id: str
    task_names: list[str]


@dataclass(frozen=True)
class EvalEndEvent:
    logs: EvalLogs


@dataclass(frozen=True)
class SampleStartedEvent:
    sample_summary: EvalSampleSummary


@dataclass(frozen=True)
class SampleScoredEvent:
    sample_summary: EvalSampleSummary


@dataclass(frozen=True)
class ModelUsageEvent:
    model_name: str
    usage: ModelUsage
    call_duration: float | None = None


# TODO: Can a user runs multiple evals in parallel with asyncio gather? If so, should we
# be providing a run_id or similar in all events to distinguish runs?
# TODO: Consider adding "tool used" event (for web_search logging).
class LifecycleHook:
    async def on_eval_start(self, event: EvalStartEvent) -> None:
        pass

    async def on_eval_end(self, event: EvalEndEvent) -> None:
        pass

    async def on_sample_started(self, event: SampleStartedEvent) -> None:
        pass

    async def on_sample_scored(self, event: SampleScoredEvent) -> None:
        pass

    # TODO: Should we have an on_sample_error event? Would need to document that this
    # can be called multiple times for the same sample if retrying.

    # TODO: Should we have an override_api_key event (which may return a value)?

    # TODO: Hook for web search usage (requested by Iman).

    async def on_model_usage(self, event: ModelUsageEvent) -> None:
        pass


T = TypeVar("T", bound=LifecycleHook)


def lifecycle_hook(name: str) -> Callable[..., Type[T]]:
    """Decorator for registering a lifecycle hook subscriber.

    Args:
        name (str): Name of the subscriber.
    """

    def wrapper(hook_type: Type[T] | Callable[..., Type[T]]) -> Type[T]:
        # Resolve the hook type it's a function.
        if not isinstance(hook_type, type):
            hook_type = hook_type()
        if not issubclass(hook_type, LifecycleHook):
            raise TypeError(
                f"Lifecycle hook must be a subclass of LifecycleHook, got {hook_type}"
            )

        # Instantiate an instance of the hook class.
        hook_instance = hook_type()
        hook_name = registry_name(hook_instance, name)
        registry_add(
            hook_instance,
            RegistryInfo(type="lifecycle_hook", name=hook_name),
        )
        return cast(Type[T], hook_instance)

    return wrapper


async def emit_eval_start(run_id: str, tasks: list[ResolvedTask]) -> None:
    event = EvalStartEvent(run_id=run_id, task_names=[task.task.name for task in tasks])
    await _emit_to_all(lambda hook: hook.on_eval_start(event))


async def emit_eval_end(logs: EvalLogs) -> None:
    event = EvalEndEvent(logs=logs)
    await _emit_to_all(lambda hook: hook.on_eval_end(event))


async def emit_sample_started(sample_summary: EvalSampleSummary) -> None:
    event = SampleStartedEvent(sample_summary)
    await _emit_to_all(lambda hook: hook.on_sample_started(event))


async def emit_sample_scored(sample_summary: EvalSampleSummary) -> None:
    event = SampleScoredEvent(sample_summary)
    await _emit_to_all(lambda hook: hook.on_sample_scored(event))


async def emit_model_usage(
    model_name: str, usage: ModelUsage, call_duration: float | None
) -> None:
    event = ModelUsageEvent(
        model_name=model_name, usage=usage, call_duration=call_duration
    )
    await _emit_to_all(lambda hook: hook.on_model_usage(event))


def get_all_lifecycle_hooks() -> list[LifecycleHook]:
    """Get all registered lifecycle hooks."""
    # TODO: Do we allow hooks to register themselves, or do we need to check that there
    # is some env var set to avoid potential attacks like we do for "INSPECT_TELEMETRY"?
    # (especially if we add an API key override hook)
    results = registry_find(lambda info: info.type == "lifecycle_hook")
    return cast(list[LifecycleHook], results)


async def _emit_to_all(callable: Callable[[LifecycleHook], Awaitable[None]]) -> None:
    for hook in get_all_lifecycle_hooks():
        try:
            await callable(hook)
        except Exception as ex:
            logger.warning(
                f"Exception calling lifecycle hook '{hook.__class__.__name__}': {ex}"
            )
            raise
