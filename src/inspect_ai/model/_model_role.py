from typing import Any, Self

from pydantic import BaseModel, Field, field_serializer, model_validator

from ._model_config import ModelConfig, model_args_for_log


class ModelRole(BaseModel):
    """Reference to a named model role, including its resolution policy."""

    name: str
    """Name of the model role."""

    required: bool = False
    """Whether a model must be bound to the role."""

    default: str | ModelConfig | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    """Default model used by model-graded scorers when the role is not bound.

    Resolved at scoring time. Cannot be combined with `required=True`.
    """

    def __init__(
        self,
        name: str,
        required: bool = False,
        *,
        default: str | ModelConfig | None = None,
    ) -> None:
        super().__init__(name=name, required=required, default=default)

    @model_validator(mode="after")
    def _validate_default(self) -> Self:
        if self.required and self.default is not None:
            raise ValueError("A required model role cannot have a default.")
        return self

    @field_serializer("default")
    def _serialize_default(
        self, default: str | ModelConfig | None
    ) -> str | ModelConfig | None:
        if isinstance(default, ModelConfig):
            return default.model_copy(update={"args": model_args_for_log(default.args)})
        return default


def as_model_role(model_role: str | ModelRole | dict[str, Any]) -> ModelRole:
    """Convert a model role name or serialized model role to `ModelRole`."""
    if isinstance(model_role, ModelRole):
        return model_role
    elif isinstance(model_role, str):
        return ModelRole(model_role)
    else:
        return ModelRole.model_validate(model_role)
