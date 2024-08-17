from inspect_ai.log._log import EvalError, eval_error

# TODO: Need to mark eval status as partially successful (sample_errors: x)
# TODO: retryable_evals needs to check for this status

# TODO: Unit tests for all scenarios
# TODO: Reducers need to not reduce when samples have errors. Do we need
#       to report failed samples w/ epochs in mind?
# TODO: Log viewer needs to denote samples with errors and have an error tab


class SampleErrorHandler:
    def __init__(self, fail_on_error: bool | float | None, total_samples: int) -> None:
        self.error_count = 0.0
        self.fail_on_error = True if fail_on_error is None else fail_on_error
        self.total_samples = float(total_samples)

    def __call__(self, ex: BaseException) -> EvalError:
        # increment error count
        self.error_count += 1

        # create error (we may return it)
        def sample_error() -> EvalError:
            return eval_error(ex, type(ex), ex, ex.__traceback__)

        # check against limits
        if isinstance(self.fail_on_error, bool):
            if self.fail_on_error:
                raise ex
            else:
                return sample_error()
        else:
            if self.fail_on_error < 1:
                max_errors = self.fail_on_error * self.total_samples
                if self.error_count >= max_errors:
                    raise ex
                else:
                    return sample_error()
            elif self.error_count >= self.fail_on_error:
                raise ex
            else:
                return sample_error()
