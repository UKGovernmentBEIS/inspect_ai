_http_retries_count: int = 0


def report_http_retry() -> None:
    from inspect_ai.log._samples import report_active_sample_retry

    # bump global counter
    global _http_retries_count
    _http_retries_count = _http_retries_count + 1

    # report sample retry
    report_active_sample_retry()


def http_retries_count() -> int:
    return _http_retries_count
