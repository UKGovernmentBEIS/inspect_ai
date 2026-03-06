from inspect_ai._util.error import EvalError
from inspect_ai.log._log import eval_error


def _should_eval_fail(
    sample_error_count: int, total_sample_count: int, fail_on_error: bool | float | None
) -> bool:
    if fail_on_error is False:
        # if fail_on_error is False, we never fail
        return False
    elif fail_on_error is None or fail_on_error is True:
        # if fail_on_error is None or True, we fail if there is any error
        return sample_error_count > 0
    else:
        if fail_on_error < 1:
            # if fail_on_error is less than 1, we make a fractional check of errors
            return sample_error_count >= fail_on_error * total_sample_count
        else:
            # if fail_on_error is larger than 1, we check the absolute count of errors
            return sample_error_count >= fail_on_error


class SampleErrorHandler:
    def __init__(self, fail_on_error: bool | float | None, total_samples: int) -> None:
        self.error_count = 0
        self.fail_on_error = True if fail_on_error is None else fail_on_error
        self.total_samples = total_samples

    def __call__(self, ex: BaseException) -> tuple[EvalError, BaseException | None]:
        # increment error count
        self.error_count += 1

        # create error (we may return it)
        def sample_error(
            *, raise_error: bool
        ) -> tuple[EvalError, BaseException | None]:
            return eval_error(
                ex, type(ex), ex, ex.__traceback__
            ), ex if raise_error else None

        # check against limits
        raise_error = _should_eval_fail(
            self.error_count, self.total_samples, self.fail_on_error
        )
        return sample_error(raise_error=raise_error)
