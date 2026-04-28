from inspect_scout import Scanner, Transcript

from inspect_ai.log._log import EvalSample


async def scan_eval_sample(
    eval_sample: EvalSample,
    scanner: Scanner[Transcript] | list[Scanner[Transcript]] | None,
) -> None:
    """Run scanner(s) over a completed sample's transcript.

    This is a stub: building a scout `Transcript` from an `EvalSample` and
    delivering scanner results requires new scout API. For now this is a
    no-op aside from normalizing `scanner` into a list.
    """
    if scanner is None:
        return
    scanners = scanner if isinstance(scanner, list) else [scanner]
    if not scanners:
        return
    # TODO: convert eval_sample to inspect_scout.Transcript and invoke each
    # scanner via a new scout API; persist results.
