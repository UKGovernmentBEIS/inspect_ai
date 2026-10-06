from typing import Any

from pydantic import BaseModel


class ModelRole(BaseModel):
    """Reference to a named model role, including its resolution policy."""

    name: str
    """Name of the model role."""

    required: bool = False
    """Whether a model must be bound to the role."""

    def __init__(self, name: str, required: bool = False) -> None:
        super().__init__(name=name, required=required)


def as_model_role(model_role: str | ModelRole | dict[str, Any]) -> ModelRole:
    """Convert a model role name or serialized model role to `ModelRole`."""
    if isinstance(model_role, ModelRole):
        return model_role
    elif isinstance(model_role, str):
        return ModelRole(model_role)
    else:
        return ModelRole.model_validate(model_role)
