import logging
from typing import Iterable

_task_names: set[str] = set()
_max_epochs: int = 1


def set_run_shape(task_names: Iterable[str], max_epochs: int) -> None:
    global _max_epochs
    _task_names.clear()
    _task_names.update(task_names)
    _max_epochs = max_epochs


class SampleContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from inspect_ai.log._samples import sample_active

        active = sample_active()
        if active is None:
            return True

        record.task = active.task
        record.sample_id = active.sample.id
        record.epoch = active.epoch

        parts = [f"sample={active.sample.id}"]
        if len(_task_names) > 1:
            parts.insert(0, f"task={active.task}")
        if _max_epochs > 1:
            parts.append(f"epoch={active.epoch}")

        formatted = record.getMessage()
        record.msg = f"{' '.join(parts)}\n{formatted}"
        record.args = None
        return True


def install_sample_context_filter(handler: logging.Handler) -> None:
    if not any(isinstance(f, SampleContextFilter) for f in handler.filters):
        handler.addFilter(SampleContextFilter())
