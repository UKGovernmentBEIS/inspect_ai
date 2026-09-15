from copy import deepcopy
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from inspect_ai._eval.task import Epochs
from inspect_ai._util.config import resolve_args
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.log._log import EvalConfig
from inspect_ai.model import GenerateConfig
from inspect_ai.model._model_config import ModelConfig, model_config_to_model
from inspect_ai.scorer._reducer import create_reducers
from inspect_ai.solver._solver import SolverSpec
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec, parse_sandbox


class TaskInput(BaseModel):
    task: str
    args: dict[str, Any] = Field(default_factory=dict)


class SolverInput(BaseModel):
    solver: str
    args: dict[str, Any] = Field(default_factory=dict)


class RunConfig(BaseModel):
    """Configuration for an evaluation run.

    Uses the same schema as the CLI's ``--run-config`` YAML or JSON file.
    All fields are optional. Validation does not instantiate models or load
    tasks and solvers; call ``to_params()`` to prepare evaluation arguments.
    """

    model_config = ConfigDict(extra="forbid")

    task: str | TaskInput | None = None
    """Task name or path, optionally with task arguments."""
    model: str | ModelConfig | None = None
    """Model name or model configuration."""
    model_roles: dict[str, ModelConfig | list[ModelConfig]] = Field(
        default_factory=dict
    )
    """Model configurations assigned to named roles."""
    generate_config: GenerateConfig = Field(default_factory=GenerateConfig)
    """Generation settings, overriding settings in the main model configuration."""
    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    """Evaluation settings."""
    solver: str | SolverInput | None = None
    """Solver name or path, optionally with solver arguments."""
    tags: list[str] = Field(default_factory=list)
    """Tags for the evaluation."""
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Metadata for the evaluation."""
    sandbox: str | SandboxEnvironmentSpec | None = None
    """Sandbox specification or ``type[:config]`` shorthand."""

    @field_validator("generate_config", mode="before")
    @classmethod
    def check_generate_config_fields(cls, v: Any) -> Any:
        if isinstance(v, dict):
            unknown = set(v.keys()) - set(GenerateConfig.model_fields.keys())
            if unknown:
                raise ValueError(f"Unknown generate_config fields: {unknown}")
        return v

    @field_validator("eval_config", mode="before")
    @classmethod
    def check_eval_config_fields(cls, v: Any) -> Any:
        if isinstance(v, dict):
            unknown = set(v.keys()) - set(EvalConfig.model_fields.keys())
            if unknown:
                raise ValueError(f"Unknown eval_config fields: {unknown}")
        return v

    def to_params(self, resolve_models: bool = True) -> dict[str, Any]:
        """Convert the configuration to keyword arguments for ``eval()``.

        Args:
            resolve_models: Instantiate models for model roles (the CLI default).
                If False, retain their ``ModelConfig`` objects, which ``eval()``
                accepts and resolves when running the evaluation. The main model
                is always represented by its name and separate configuration args.

        Returns:
            Evaluation keyword arguments, with generation settings flattened.
        """
        params: dict[str, Any] = {}

        # Task
        if self.task is not None:
            if isinstance(self.task, str):
                params["tasks"] = self.task
            else:
                params["tasks"] = self.task.task
                if self.task.args:
                    params["task_args"] = self.task.args

        # Model
        if self.model is not None:
            if isinstance(self.model, str):
                params["model"] = self.model
            else:
                params["model"] = self.model.model
                if self.model.base_url is not None:
                    params["model_base_url"] = self.model.base_url
                if self.model.args:
                    params["model_args"] = self.model.args
                model_gc = self.model.config.model_dump(exclude_none=True)
                if model_gc:
                    params.update(model_gc)

        # Top-level generate_config overrides any model-level config
        top_gc = self.generate_config.model_dump(exclude_none=True)
        if top_gc:
            params.update(top_gc)

        # Model roles
        if self.model_roles:
            if resolve_models:
                params["model_roles"] = {
                    role: [model_config_to_model(m) for m in mc]
                    if isinstance(mc, list)
                    else model_config_to_model(mc)
                    for role, mc in self.model_roles.items()
                }
            else:
                params["model_roles"] = deepcopy(self.model_roles)

        # Solver
        if self.solver is not None:
            if isinstance(self.solver, str):
                params["solver"] = SolverSpec(self.solver, {}, {})
            else:
                params["solver"] = SolverSpec(
                    self.solver.solver, self.solver.args, self.solver.args
                )

        # Eval config — combine epochs + epochs_reducer into Epochs
        ec = self.eval_config.model_dump(exclude_none=True)
        epochs = ec.pop("epochs", None)
        epochs_reducer = ec.pop("epochs_reducer", None)
        if epochs is not None:
            ec["epochs"] = Epochs(epochs, create_reducers(epochs_reducer))
        params.update(ec)

        # Tags and metadata
        if self.tags:
            params["tags"] = self.tags
        if self.metadata:
            params["metadata"] = self.metadata

        # Sandbox
        if self.sandbox is not None:
            if isinstance(self.sandbox, str):
                params["sandbox"] = parse_sandbox(self.sandbox)
            else:
                params["sandbox"] = self.sandbox

        return params


RunConfigInput = RunConfig


def read_run_config(path: str) -> RunConfig:
    """Read and validate an evaluation run configuration without resolving models.

    Args:
        path: YAML or JSON configuration file (local path, file URI, or remote
            filesystem URL such as ``s3://bucket/run.yaml``).

    Returns:
        Validated configuration. Call ``to_params()`` to prepare eval arguments.

    Raises:
        PrerequisiteError: The file does not exist or fails schema validation.
        ValueError: The file cannot be parsed as a configuration object.
    """
    from jsonschema import Draft7Validator

    config_dict = resolve_args(path)
    try:
        run_config = RunConfig.model_validate(config_dict)
    except ValidationError as ex:
        # Surface a more readable error via Draft7Validator. Fall back to
        # pydantic's message when the JSON schema doesn't capture the
        # failure (e.g. custom field_validators on generate_config/eval_config).
        schema = RunConfig.model_json_schema()
        errors = list(Draft7Validator(schema).iter_errors(config_dict))
        if errors:
            message = "\n".join(
                [f"Invalid run config '{path}':"]
                + [f" - {error.message}" for error in errors]
            )
        else:
            message = f"Invalid run config '{path}': {ex}"
        raise PrerequisiteError(message)
    return run_config


def merge_run_config_params(
    run_params: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Merge evaluation overrides using the CLI's run-configuration precedence.

    Args:
        run_params: Base evaluation arguments, typically from ``RunConfig.to_params``.
        overrides: Overrides. ``None``, empty dictionaries, and ``score=True``
            are ignored, matching CLI defaults. Task arguments, model arguments,
            and model roles merge by key; all other supplied values replace.

    Returns:
        Merged arguments in a new dictionary, without modifying either input.
    """
    params = dict(run_params)
    for key, value in overrides.items():
        if value is None or value == {}:
            continue
        if key == "score" and value is True:
            continue
        if key in ("task_args", "model_args") and key in params:
            params[key] = params[key] | value
        elif key == "model_roles" and key in params:
            params[key] = params[key] | value
        else:
            params[key] = value
    return params
