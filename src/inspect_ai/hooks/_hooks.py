from dataclasses import dataclass
from logging import getLogger
from typing import Awaitable, Callable, Type, TypeVar, cast

from inspect_ai._eval.eval import EvalLogs
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._util.error import EvalError
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_find,
    registry_name,
)
from inspect_ai.hooks._legacy import override_api_key_legacy
from inspect_ai.log._log import EvalLog, EvalSampleSummary, EvalSpec
from inspect_ai.model._model_output import ModelUsage

logger = getLogger(__name__)


@dataclass(frozen=True)
class RunStart:
    """Run start hook event data."""

    run_id: str
    task_names: list[str]


@dataclass(frozen=True)
class RunEnd:
    """Run end hook event data."""

    run_id: str
    logs: EvalLogs


@dataclass(frozen=True)
class TaskStart:
    """Task start hook event data."""

    run_id: str
    eval_id: str
    spec: EvalSpec


@dataclass(frozen=True)
class TaskEnd:
    """Task end hook event data."""

    run_id: str
    eval_id: str
    log: EvalLog


@dataclass(frozen=True)
class SampleStart:
    """Sample start hook event data."""

    run_id: str
    eval_id: str
    sample_id: int | str
    summary: EvalSampleSummary


@dataclass(frozen=True)
class SampleEnd:
    """Sample end hook event data."""

    run_id: str
    eval_id: str
    sample_id: int | str
    summary: EvalSampleSummary


@dataclass(frozen=True)
class SampleAbort:
    """Sample abort hook event data."""

    run_id: str
    eval_id: str
    sample_id: int | str
    error: EvalError


@dataclass(frozen=True)
class ModelUsageData:
    """Model usage hook event data."""

    model_name: str
    usage: ModelUsage
    call_duration: float | None = None


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

        If a sample is run for multiple epochs, this will be called once per epoch.

        If a sample is retried, this will be called again for each new attempt.

        Args:
           data: Sample start data.
        """
        pass

    async def on_sample_end(self, data: SampleEnd) -> None:
        """On sample end.

        This will be called when a sample has completed without error. If there are
        multiple epochs for a sample, this will be called once per successfully
        completed epoch.

        Args:
           data: Sample end data.
        """
        pass

    async def on_sample_abort(self, data: SampleAbort) -> None:
        """A sample has been aborted due to an error, and will not be retried.

        If there are multiple epochs for a sample, this will be called once per
        aborted epoch of the sample.

        Args:
           data: Sample end data.
        """
        pass

    async def on_model_usage(self, data: ModelUsageData) -> None:
        """Called when a call to a model's generate() method completes successfully.

        Args:
           data: Model usage data.
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


def hooks(name: str) -> Callable[..., Type[T]]:
    """Decorator for registering a hook subscriber.

    Either decorate a subclass of `Hooks`, or a function which returns the type
    of a subclass of `Hooks`. This decorator will instantiate the hook class
    and store it in the registry.

    Args:
        name (str): Name of the subscriber.
    """

    def wrapper(hook_type: Type[T] | Callable[..., Type[T]]) -> Type[T]:
        # Resolve the hook type it's a function.
        if not isinstance(hook_type, type):
            hook_type = hook_type()
        if not issubclass(hook_type, Hooks):
            raise TypeError(f"Hook must be a subclass of Hooks, got {hook_type}")

        # Instantiate an instance of the hook class.
        hook_instance = hook_type()
        hook_name = registry_name(hook_instance, name)
        registry_add(
            hook_instance,
            RegistryInfo(type="hooks", name=hook_name),
        )
        return cast(Type[T], hook_instance)

    return wrapper


async def emit_run_start(run_id: str, tasks: list[ResolvedTask]) -> None:
    data = RunStart(run_id=run_id, task_names=[task.task.name for task in tasks])
    await _emit_to_all(lambda hook: hook.on_run_start(data))


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
    run_id: str, eval_id: str, sample_id: int | str, summary: EvalSampleSummary
) -> None:
    data = SampleStart(
        run_id=run_id, eval_id=eval_id, sample_id=sample_id, summary=summary
    )
    await _emit_to_all(lambda hook: hook.on_sample_start(data))


async def emit_sample_end(
    run_id: str, eval_id: str, sample_id: int | str, summary: EvalSampleSummary
) -> None:
    data = SampleEnd(
        run_id=run_id, eval_id=eval_id, sample_id=sample_id, summary=summary
    )
    await _emit_to_all(lambda hook: hook.on_sample_end(data))


async def emit_sample_abort(
    run_id: str, eval_id: str, sample_id: int | str, error: EvalError
) -> None:
    data = SampleAbort(run_id=run_id, eval_id=eval_id, sample_id=sample_id, error=error)
    await _emit_to_all(lambda hook: hook.on_sample_abort(data))


async def emit_model_usage(
    model_name: str, usage: ModelUsage, call_duration: float | None
) -> None:
    data = ModelUsageData(
        model_name=model_name, usage=usage, call_duration=call_duration
    )
    await _emit_to_all(lambda hook: hook.on_model_usage(data))


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
