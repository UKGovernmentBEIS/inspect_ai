# temporary file to experiment with limits
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._limit import (
    LimitExceededError,
    apply_limits,
    check_token_limit,
    message_limit,
    record_model_usage,
    token_limit,
)

with token_limit(5):
    tl = token_limit(10)
    try:
        with tl:
            record_model_usage(ModelUsage(total_tokens=6))
            check_token_limit()
    except LimitExceededError as e:
        if e.source is tl:
            print("My limit exceeded")
        else:
            print("Other limit exceeded")


with token_limit(100):
    with apply_limits([token_limit(10), message_limit(10)]) as limit_scope:
        record_model_usage(ModelUsage(total_tokens=60))
        check_token_limit()
    print(f"Was my limit exceeded {limit_scope.were_any_exceeded}")
