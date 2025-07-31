from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

MT = TypeVar("MT", bound=BaseModel)


def metadata_as(metadata: dict[str, Any], metadata_cls: Type[MT]) -> MT:
    # validate that metadata_cls is frozen
    if not metadata_cls.model_config.get("frozen", False):
        raise ValueError(
            f"Metadata model {metadata_cls.__name__} must have frozen=True"
        )

    # filter to only fields in the model
    model_fields = {
        k: v
        for k, v in metadata.items()
        if k in metadata_cls.__pydantic_fields__.keys()
    }

    # parse and return model instance
    try:
        return metadata_cls(**model_fields)
    except ValidationError as ex:
        raise ValueError(f"Could not parse metadata into {metadata_cls.__name__}: {ex}")
