"""Parsing for the ``--run-config`` option of ``inspect eval``.

Kept in its own module so that ``_cli/eval.py`` can stay import-light: the
pydantic models below reference ``GenerateConfig`` / ``EvalConfig`` /
``ModelConfig`` / ``SandboxEnvironmentSpec`` in their field annotations, which
forces those (heavy) modules to be imported at class-definition time. By
isolating them here and importing this module lazily inside the command
callbacks, ``inspect eval --help`` avoids paying that cost.
"""

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from inspect_ai import Epochs
from inspect_ai._util.config import resolve_args
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.log._log import EvalConfig
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._model_config import ModelConfig
from inspect_ai.scorer._reducer import create_reducers
from inspect_ai.solver._solver import SolverSpec
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

from .util import parse_sandbox


class TaskInput(BaseModel):
    task: str
    args: dict[str, Any] = Field(default_factory=dict)


class SolverInput(BaseModel):
    solver: str
    args: dict[str, Any] = Field(default_factory=dict)


class RunConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | TaskInput | None = None
    model: str | ModelConfig | None = None
    model_roles: dict[str, ModelConfig] = Field(default_factory=dict)
    generate_config: GenerateConfig = Field(default_factory=GenerateConfig)
    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    solver: str | SolverInput | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sandbox: str | SandboxEnvironmentSpec | None = None

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

    def to_params(self) -> dict[str, Any]:
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
            params["model_roles"] = {
                role: get_model(
                    mc.model, config=mc.config, base_url=mc.base_url, **mc.args
                )
                for role, mc in self.model_roles.items()
            }

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


def parse_run_config(config: str) -> dict[str, Any]:
    from jsonschema import Draft7Validator

    config_dict = resolve_args(config)
    try:
        run_config = RunConfigInput.model_validate(config_dict)
    except ValidationError as ex:
        # Surface a more readable error via Draft7Validator. Fall back to
        # pydantic's message when the JSON schema doesn't capture the
        # failure (e.g. custom field_validators on generate_config/eval_config).
        schema = RunConfigInput.model_json_schema()
        errors = list(Draft7Validator(schema).iter_errors(config_dict))
        if errors:
            message = "\n".join(
                [f"Invalid run config '{config}':"]
                + [f" - {error.message}" for error in errors]
            )
        else:
            message = f"Invalid run config '{config}': {ex}"
        raise PrerequisiteError(message)
    return run_config.to_params()


def merge_run_config_params(
    run_params: dict[str, Any], cli_params: dict[str, Any]
) -> dict[str, Any]:
    params = dict(run_params)
    for key, value in cli_params.items():
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
