from logging import getLogger

logger = getLogger(__name__)


def report_refusal(refusal: str) -> None:
    from inspect_ai.log._samples import sample_active

    # update counter
    global _refusal_count
    _refusal_count = _refusal_count + 1

    # log warning
    active = sample_active()
    if active:
        sample = f" ({active.task}/{active.id}/{active.epoch})"
    else:
        sample = ""
    warning = f"Model refusal{sample}: {refusal}"
    logger.warning(warning)


def refusal_count() -> int:
    return _refusal_count


def init_refusal_count() -> None:
    global _refusal_count
    _refusal_count = 0


_refusal_count: int = 0
