import inspect
import sys

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from .agent import ANSWER_FUNC_TIMEOUT

VERIFICATION_CODE_TIMEOUT = 120

# When `verify()` returns True or False (100-101)
EXIT_VERIFY_TRUE = 100
EXIT_VERIFY_FALSE = 101
# Errors in the `answer()` function (102-103)
EXIT_ANSWER_ERROR = 102
EXIT_ANSWER_TIMEOUT = 103
# Errors in the `verify()` function (104)
EXIT_VERIFY_ERROR = 104


@scorer(metrics=[accuracy(), stderr()], name="verification_code")
def verification_code_scorer() -> Scorer:
    """Score a FrontierMath problem submission."""

    async def score(state: TaskState, target: Target) -> Score:
        # Get the submitted answer
        answer_code = state.store.get("submitted_answer")
        if answer_code is None:
            return Score(value=INCORRECT, explanation="No solution submitted")

        answer_code_backticks = f"```python\n{answer_code}\n```"

        scoring_code = f"""
import sys
{inspect.getsource(ExitOnException)}
{inspect.getsource(WithTimeout)}
{answer_code}
{state.metadata["verification_code"]}
with ExitOnException(exit_code={EXIT_ANSWER_ERROR}), WithTimeout({ANSWER_FUNC_TIMEOUT}, {EXIT_ANSWER_TIMEOUT}):
    a = answer()
with ExitOnException(exit_code={EXIT_VERIFY_ERROR}):
    is_correct = verify(a)

if is_correct:
    sys.exit({EXIT_VERIFY_TRUE})
else:
    sys.exit({EXIT_VERIFY_FALSE})
"""

        try:
            # Execute the verification code in the sandbox
            result = await sandbox().exec(
                ["python3", "-c", scoring_code], timeout=VERIFICATION_CODE_TIMEOUT
            )
        except TimeoutError:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Verification code execution timed out (timeout: {VERIFICATION_CODE_TIMEOUT} seconds)",
            )

        if result.returncode == EXIT_VERIFY_TRUE:
            return Score(
                answer=answer_code_backticks,
                value=CORRECT,
                explanation="The `verify()` function returned True",
            )
        elif result.returncode == EXIT_VERIFY_FALSE:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation="The `verify()` function returned False",
            )
        # Answer function errors
        elif result.returncode == EXIT_ANSWER_ERROR:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Error while executing the `answer()` function:\n{result.stderr}",
            )
        elif result.returncode == EXIT_ANSWER_TIMEOUT:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Error while executing the `answer()` function: Timeout exceeded (timeout: {ANSWER_FUNC_TIMEOUT} seconds)",
            )
        # Verification function errors
        elif result.returncode == EXIT_VERIFY_ERROR:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Error while executing the `verify()` function:\n{result.stderr}",
            )

        # Other errors with exit code 1
        elif result.returncode == 1:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Error in verification code:\n{result.stderr}",
            )
        else:
            return Score(
                answer=answer_code_backticks,
                value=INCORRECT,
                explanation=f"Unknown failure in verification code:\n{result.stderr}",
            )

    return score


class ExitOnException:
    """A context manager that prints the traceback and exits on exception."""

    def __init__(self, exit_code: int = 1):
        self.exit_code = exit_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import traceback

        if exc_type is not None and exc_type is not SystemExit:
            traceback.print_exception(exc_type, exc_val, exc_tb, file=sys.stderr)
            sys.exit(self.exit_code)
        return False


class WithTimeout:
    """Signal-based timeout context manager."""

    def __init__(self, timeout_sec: int, exit_code: int):
        self.timeout_sec = timeout_sec
        self.exit_code = exit_code

    def _handle_alarm(self, signum, frame):
        print("Timeout while calling answer()", file=sys.stderr)
        sys.exit(self.exit_code)

    def __enter__(self):
        import signal

        signal.signal(signal.SIGALRM, self._handle_alarm)
        signal.alarm(self.timeout_sec)

    def __exit__(self, exc_type, exc_val, exc_tb):
        import signal

        signal.alarm(0)
        return False
