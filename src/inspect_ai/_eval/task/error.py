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
    def __init__(
        self,
        fail_on_error: bool | float | None,
        total_samples: int,
        defer_fractional: bool = False,
    ) -> None:
        """Handle sample errors, aborting the eval when `fail_on_error` says to.

        Args:
            fail_on_error: `True` to fail on any error, a fraction (< 1) of
                `total_samples`, or an absolute count (>= 1).
            total_samples: Planned sample runs (denominator for fractional
                thresholds). May be grown while running (`SampleSource`).
            defer_fractional: Don't abort mid-run on a fractional threshold —
                leave it to the end-of-run check. Used by `SampleSource`-driven
                tasks, whose planned total grows while they run: an early error
                would otherwise be measured against a transiently small
                denominator (e.g. a 1-sample seed erroring trips `1 >= 0.5*1`
                before the source has produced the rest). Absolute-count and
                any-error thresholds don't depend on the denominator and still
                abort mid-run.
        """
        self.error_count = 0
        self.fail_on_error = True if fail_on_error is None else fail_on_error
        self.total_samples = total_samples
        self.defer_fractional = defer_fractional

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
        if self.defer_fractional and self._is_fractional():
            raise_error = False
        else:
            raise_error = _should_eval_fail(
                self.error_count, self.total_samples, self.fail_on_error
            )
        return sample_error(raise_error=raise_error)

    def _is_fractional(self) -> bool:
        return not isinstance(self.fail_on_error, bool) and 0 < self.fail_on_error < 1
