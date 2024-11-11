from typing import Any, Callable, Literal, cast

from .eval import EvalRecorder
from .json import JSONRecorder
from .recorder import Recorder

_recorders: dict[str, type[Recorder]] = {"eval": EvalRecorder, "json": JSONRecorder}


def create_recorder_for_format(
    format: Literal["eval", "json"], *args: Any, **kwargs: Any
) -> Recorder:
    recorder = recorder_type_for_format(format)
    return recorder(*args, **kwargs)


def recorder_type_for_format(format: Literal["eval", "json"]) -> type[Recorder]:
    recorder = _recorders.get(format, None)
    if recorder:
        return recorder
    else:
        raise ValueError(f"No recorder for format: {format}")


def create_recorder_for_location(location: str, log_dir: str) -> Recorder:
    recorder = recorder_type_for_location(location)
    return cast(Callable[[str], Recorder], recorder)(log_dir)


def recorder_type_for_location(location: str) -> type[Recorder]:
    for recorder in _recorders.values():
        if recorder.handles_location(location):
            return recorder

    raise ValueError(f"No recorder for location: {location}")
