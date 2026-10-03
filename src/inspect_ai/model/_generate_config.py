from contextvars import ContextVar

from inspect_ai._util.constants import DEFAULT_BATCH_SIZE
from inspect_ai.core._generate_config import (
    BatchConfig as BatchConfig,
)
from inspect_ai.core._generate_config import (
    GenerateConfig as GenerateConfig,
)
from inspect_ai.core._generate_config import (
    GenerateConfigArgs as GenerateConfigArgs,
)
from inspect_ai.core._generate_config import (
    ImageOutput as ImageOutput,
)
from inspect_ai.core._generate_config import (
    OutputModality as OutputModality,
)
from inspect_ai.core._generate_config import (
    ResponseSchema as ResponseSchema,
)


def active_generate_config() -> GenerateConfig:
    return active_generate_config_context_var.get()


def set_active_generate_config(config: GenerateConfig) -> None:
    active_generate_config_context_var.set(config)


active_generate_config_context_var: ContextVar[GenerateConfig] = ContextVar(
    "generate_config", default=GenerateConfig()
)


def has_image_output(modalities: list[OutputModality] | None) -> bool:
    """Check if modalities include image output."""
    return image_output_config(modalities) is not None


def image_output_config(
    modalities: list[OutputModality] | None,
) -> ImageOutput | None:
    """Return the last ImageOutput from modalities.

    Returns a default ImageOutput if only string "image" entries exist,
    or None if no image output is present.
    """
    if modalities is None:
        return None
    last: ImageOutput | None = None
    found = False
    for m in modalities:
        if m == "image" or isinstance(m, ImageOutput):
            found = True
            if isinstance(m, ImageOutput):
                last = m
    if not found:
        return None
    return last if last is not None else ImageOutput()


def normalized_batch_config(
    batch: bool | int | BatchConfig | None,
) -> BatchConfig | None:
    return (
        batch
        if isinstance(batch, BatchConfig)
        else None
        if not batch
        else BatchConfig(size=DEFAULT_BATCH_SIZE if batch is True else batch)
    )
