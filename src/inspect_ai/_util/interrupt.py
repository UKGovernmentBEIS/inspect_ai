import asyncio


def check_sample_interrupt() -> None:
    from inspect_ai.log._samples import sample_active

    sample = sample_active()
    if sample and sample.interrupt_action:
        raise asyncio.CancelledError()
