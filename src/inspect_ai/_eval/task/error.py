from inspect_ai._util.error import EvalError
from inspect_ai.log._log import eval_error


class SampleErrorHandler:
    def __init__(self, fail_on_error: bool | float | None, total_samples: int) -> None:
        self.error_count = 0.0
        self.fail_on_error = True if fail_on_error is None else fail_on_error
        self.total_samples = float(total_samples)

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
        if isinstance(self.fail_on_error, bool):
            return sample_error(raise_error=self.fail_on_error)
        else:
            if self.fail_on_error < 1:
                max_errors = self.fail_on_error * self.total_samples
                return sample_error(raise_error=self.error_count >= max_errors)
            else:
                return sample_error(raise_error=self.error_count >= self.fail_on_error)
