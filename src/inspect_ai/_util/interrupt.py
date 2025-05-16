import anyio

from .working import check_sample_working_limit


def check_sample_interrupt() -> None:
    from inspect_ai.log._samples import sample_active

    # check for user interrupt
    sample = sample_active()
    if sample and sample.interrupt_action:
        raise anyio.get_cancelled_exc_class()

    # check for working_limit
    check_sample_working_limit()
