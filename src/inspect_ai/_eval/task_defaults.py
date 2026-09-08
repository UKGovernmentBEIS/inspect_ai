"""Framework-only task defaults, scoped to one evaluation invocation.

Factories and constructed Tasks never consult this module on direct calls.
Run-wide settings are agreed before initialization; per-task settings remain on
ResolvedTask so heterogeneous sample selection and generation stay independent.
"""

import inspect
import logging
import os
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from inspect_ai._util.file import absolute_file_path, dirname, filesystem, local_path
from inspect_ai._util.registry import registry_info, registry_lookup
from inspect_ai.log import EvalConfig
from inspect_ai.model import GenerateConfig
from inspect_ai.model._model import init_model_roles, model_roles
from inspect_ai.model._util import resolve_model_roles
from inspect_ai.solver import SolverSpec

from .run_config import RunConfig, TaskInput, merge_run_config_params, read_run_config
from .task import Epochs, Task
from .task.constants import TASK_DEFAULT_CONFIG_ATTR, TASK_DEFAULT_CONFIG_SOURCE_ATTR
from .task.tasks import Tasks

PER_TASK_FIELDS = frozenset(
    {
        "limit",
        "sample_id",
        "sample_shuffle",
        "epochs",
        "epochs_reducer",
        "fail_on_error",
        "continue_on_fail",
        "retry_on_error",
        "score_on_error",
        "message_limit",
        "token_limit",
        "token_limit_type",
        "turn_limit",
        "time_limit",
        "working_limit",
        "cost_limit",
        "max_samples",
        "max_dataset_memory",
    }
)
RUN_WIDE_FIELDS = frozenset(EvalConfig.model_fields) - PER_TASK_FIELDS

logger = logging.getLogger(__name__)

_source: ContextVar[str | None] = ContextVar("run_config_source", default=None)


@dataclass(frozen=True)
class DefaultsScope:
    enabled: bool
    configs: dict[str, RunConfig]
    run_wide: dict[str, Any]


_scope: ContextVar[DefaultsScope | None] = ContextVar(
    "task_defaults_scope", default=None
)
P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def run_config_source(source: str | None) -> Iterator[None]:
    """Annotate resolved tasks with an explicitly selected run configuration."""
    token = _source.set(source)
    try:
        yield
    finally:
        _source.reset(token)


def current_run_config_source() -> str | None:
    """Return CLI provenance in the current evaluation scope, if any."""
    return _source.get()


def defaults_enabled() -> bool:
    """Whether framework construction may load an attached configuration."""
    scope = _scope.get()
    return scope.enabled if scope is not None else True


def default_config_path(factory: Callable[..., Any]) -> str | None:
    """Resolve an attachment relative to the unwrapped factory's source file."""
    reference = registry_info(factory).metadata.get("attribs", {}).get("default_config")
    if reference is None:
        return None
    if not isinstance(reference, str):
        raise ValueError("task default_config must be a string path")
    if filesystem(reference).is_local() and not os.path.isabs(local_path(reference)):
        source = inspect.getsourcefile(inspect.unwrap(factory))
        if source is None:
            raise ValueError(
                f"Cannot resolve task default_config '{reference}': no source file"
            )
        reference = os.path.join(dirname(source), local_path(reference))
    return absolute_file_path(reference)


def read_task_default(path: str, factory: Callable[..., Any]) -> RunConfig:
    """Read purely: validate forbidden selection even when explicitly null.

    A task reference is allowed only when it names the attached task by its
    registry name, so the file can document (and stand alone for) that task
    without being able to redirect the run.
    """
    config = read_run_config(path)
    if "model" in config.model_fields_set:
        raise ValueError(f"Task default config '{path}' cannot select a model")
    selected = config.task.task if isinstance(config.task, TaskInput) else config.task
    if selected is not None:
        attached = registry_info(factory).name
        if selected != attached:
            raise ValueError(
                f"Task default config '{path}' names task '{selected}' "
                f"but is attached to task '{attached}'"
            )
    return config


def task_default(factory: Callable[..., Any]) -> tuple[str | None, RunConfig | None]:
    """Return the current attachment, without reading anything when disabled."""
    if not defaults_enabled():
        return None, None
    path = default_config_path(factory)
    if path is None:
        return None, None
    scope = _scope.get()
    config = scope.configs.get(path) if scope is not None else None
    return path, config if config is not None else read_task_default(path, factory)


@contextmanager
def evaluation_defaults(params: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Preflight run-wide defaults before model, subprocess or server startup.

    Explicit non-null arguments win. Multiple files may agree on a run-wide
    setting; conflicting values require a caller override. Per-task defaults
    are not broadcast into this parameter dictionary.
    """
    from .loader import task_default_factories

    enabled = params.get("default_config", True)
    configs: dict[str, RunConfig] = {}
    agreed: dict[str, Any] = {}
    sources: dict[str, str] = {}
    if enabled:
        for factory in task_default_factories(cast(Tasks, params.get("tasks"))):
            path = default_config_path(factory)
            if path is None:
                continue
            config = configs.setdefault(path, read_task_default(path, factory))
            for key, value in config.eval_config.model_dump(exclude_none=True).items():
                if key not in RUN_WIDE_FIELDS or params.get(key) is not None:
                    continue
                if key in agreed and agreed[key] != value:
                    raise ValueError(
                        f"Conflicting task default '{key}' in '{sources[key]}' and '{path}'; "
                        f"supply an explicit {key} override"
                    )
                agreed[key] = value
                sources[key] = path
    effective = merge_run_config_params(agreed, params)
    token = _scope.set(
        DefaultsScope(enabled, configs, {k: effective.get(k) for k in RUN_WIDE_FIELDS})
    )
    try:
        yield effective
    finally:
        _scope.reset(token)


def with_task_defaults(fn: Callable[P, R]) -> Callable[P, R]:
    """Scope synchronous eval-set discovery and apply run-wide defaults early."""
    signature = inspect.signature(fn)

    @wraps(fn)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = signature.bind(*args, **kwargs)
        with evaluation_defaults(dict(bound.arguments)) as params:
            bound.arguments.update(params)
            return fn(*bound.args, **bound.kwargs)

    return wrapped


def with_task_defaults_async(
    fn: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Scope asynchronous evaluation, including dynamically enqueued tasks."""
    signature = inspect.signature(fn)

    @wraps(fn)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = signature.bind(*args, **kwargs)
        with evaluation_defaults(dict(bound.arguments)) as params:
            bound.arguments.update(params)
            return await fn(*bound.args, **bound.kwargs)

    return wrapped


def create_task_with_defaults(
    name: str, args: dict[str, Any], enabled: bool = True
) -> Task:
    """Construct a registry task with file arguments below explicit caller keys.

    The argument dictionary is separate from loader controls so task factories
    can use arbitrary parameter names. Role overrides are merged before model
    construction, avoiding credentials or side effects for discarded defaults.
    """
    from .loader import solver_from_spec
    from .registry import task_create

    factory = cast(Callable[..., Any] | None, registry_lookup("task", name))
    path, config = (
        task_default(factory) if factory is not None and enabled else (None, None)
    )
    if config is None or factory is None:
        return task_create(name, **args)
    params = config.to_params(resolve_models=False)
    if config.eval_config.epochs_reducer is not None and "epochs" not in params:
        params["epochs_reducer"] = config.eval_config.epochs_reducer
    scope = _scope.get()
    run_wide_keys = sorted(RUN_WIDE_FIELDS & params.keys())
    if scope is not None:
        for key in run_wide_keys:
            current = scope.run_wide.get(key)
            if current is None:
                raise ValueError(
                    f"Task default '{path}' requires run-wide '{key}={params[key]}'; configure it before starting the run"
                )
    elif run_wide_keys:
        # resolved outside eval()/eval_set() (e.g. eval_resolve_tasks from
        # Inspect Flow): there is no run to agree these for, so drop them
        # rather than record them in the log as if applied
        logger.warning(
            f"Task default '{path}' sets run-wide {run_wide_keys}, which apply "
            "only when eval(), eval_set() or the CLI resolves the task; ignored"
        )
        for key in run_wide_keys:
            params.pop(key)
    current_roles = model_roles()
    roles = resolve_model_roles(params.get("model_roles", {}) | current_roles)
    init_model_roles(roles or {})
    try:
        task = task_create(name, **(params.get("task_args", {}) | args))
    finally:
        init_model_roles(current_roles)
    generation = {k: v for k, v in params.items() if k in GenerateConfig.model_fields}
    task.config = task.config.merge(GenerateConfig(**generation))
    task.model_roles = (task.model_roles or {}) | (roles or {})
    for key in PER_TASK_FIELDS - {"epochs_reducer", "token_limit_type"}:
        if key in params and hasattr(task, key):
            value = params[key]
            if key == "epochs" and isinstance(value, Epochs):
                task.epochs = value.epochs
                if value.reducer is not None:
                    task.epochs_reducer = value.reducer
            else:
                setattr(task, key, value)
    if "token_limit_type" in params:
        task.token_limit_type = params["token_limit_type"]
    if "epochs_reducer" in params:
        from inspect_ai.scorer._reducer import create_reducers

        task.epochs_reducer = create_reducers(params["epochs_reducer"])
    if "sandbox" in params:
        task.sandbox = params["sandbox"]
    if "solver" in params:
        spec = cast(SolverSpec, params["solver"])
        file, separator, solver = spec.solver.partition("@")
        if (
            separator
            and not os.path.isabs(local_path(file))
            and filesystem(file).is_local()
        ):
            source = inspect.getsourcefile(inspect.unwrap(factory))
            if source is None:
                raise ValueError(
                    f"Cannot resolve solver '{spec.solver}' without a task source"
                )
            spec = SolverSpec(
                os.path.join(dirname(source), file) + "@" + solver,
                spec.args,
                spec.args_passed,
            )
        params["solver"] = spec
        task.solver = solver_from_spec(spec)
    if "tags" in params:
        task.tags = params["tags"]
    if "metadata" in params:
        task.metadata = (task.metadata or {}) | params["metadata"]
    setattr(task, TASK_DEFAULT_CONFIG_ATTR, params)
    setattr(task, TASK_DEFAULT_CONFIG_SOURCE_ATTR, f"task_default:{path}")
    return task


def resolve_task_eval_config(
    params: dict[str, Any], overrides: EvalConfig
) -> EvalConfig:
    """Merge per-task file evaluation settings below effective call overrides.

    Sample selection is one setting: an explicit sample_id replaces the file's
    limit and shuffle, and an explicit limit or shuffle replaces the file's
    sample_id. Otherwise a file sample_id would survive an explicit limit and
    win in slice_dataset, a combination eval() itself rejects.
    """
    defaults = {k: v for k, v in params.items() if k in EvalConfig.model_fields}
    epochs = defaults.get("epochs")
    if isinstance(epochs, Epochs):
        defaults["epochs"] = epochs.epochs
    supplied = overrides.model_dump(exclude_none=True)
    if "sample_id" in supplied:
        defaults.pop("limit", None)
        defaults.pop("sample_shuffle", None)
    if "limit" in supplied or "sample_shuffle" in supplied:
        defaults.pop("sample_id", None)
    return EvalConfig(**merge_run_config_params(defaults, supplied))
