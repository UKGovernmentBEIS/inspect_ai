from logging import getLogger

logger = getLogger(__name__)

_refusal_count: int = 0
_log_refusals: bool = False


def report_refusal(refusal: str) -> None:
    from inspect_ai.log._samples import sample_active

    # update counter
    global _refusal_count
    _refusal_count = _refusal_count + 1

    # log warning
    global _log_refusals
    if _log_refusals:
        active = sample_active()
        if active:
            sample = f" ({active.task}/{active.id}/{active.epoch})"
        else:
            sample = ""
        warning = f"Model refusal{sample}: {refusal}"
        logger.warning(warning)


def refusal_count() -> int:
    return _refusal_count


def init_refusal_tracking(log_refusals: bool | None) -> None:
    # _refusal_count is intentionally not reset here: it feeds a shared TUI
    # counter and, with INSPECT_ALLOW_CONCURRENT_EVAL_ASYNC, resetting on each
    # eval_async() entry would zero a concurrently-running eval's tally.
    global _log_refusals
    _log_refusals = log_refusals is True
