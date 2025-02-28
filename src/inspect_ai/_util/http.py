# see https://cloud.google.com/storage/docs/retry-strategy
def is_retryable_http_status(status_code: int) -> bool:
    return status_code in [408, 429] or (500 <= status_code < 600)
