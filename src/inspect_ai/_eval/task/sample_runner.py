import contextlib
import time
from logging import getLogger
from typing import Any, Awaitable, Callable

import anyio
from anyio.abc import TaskGroup

from inspect_ai._eval.task.scan import Scanners
from inspect_ai._util.error import exception_message
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.registry import (
    has_registry_params,
    registry_log_name,
    registry_params,
    registry_unqualified_name,
)
from inspect_ai._util.working import (
    init_sample_working_time,
    sample_start_datetime,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.log import EvalError, EvalSample
from inspect_ai.log._log import (
    EvalRetryError,
    EvalSampleLimit,
    EvalSampleSummary,
    eval_error,
)
from inspect_ai.log._samples import active_sample
from inspect_ai.log._transcript import (
    Transcript,
    init_transcript,
    transcript,
)
from inspect_ai.model._model import (
    init_sample_model_usage,
    init_sample_role_usage,
    sample_model_usage,
    sample_role_usage,
)
from inspect_ai.scorer import Scorer, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._score import init_scoring_context
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Plan, TaskState
from inspect_ai.solver._task_state import sample_state, set_sample_state, state_jsonable
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint
from inspect_ai.util._checkpoint.config import (
    CheckpointConfig,
    merge_checkpoint_configs,
)
from inspect_ai.util._early_stopping import EarlyStop, EarlyStopping
from inspect_ai.util._limit import (
    LimitExceededError,
    monitor_working_limit,
    record_sample_limit_data,
)
from inspect_ai.util._limit import time_limit as create_time_limit
from inspect_ai.util._limit import working_limit as create_working_limit
from inspect_ai.util._sandbox import SandboxTimeoutError
from inspect_ai.util._sandbox.context import sandbox_connections
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._span import span
from inspect_ai.util._store import init_subtask_store

from . import scan as _scan_mod
from .error import SampleErrorHandler
from .images import (
    sample_without_base64_content,
    state_without_base64_content,
    states_with_base64_content,
)
from .log import TaskLogger
from .sample_helpers import (
    create_eval_sample,
    eval_retry_error,
    init_sample_assistant_internal,
    log_sample,
)
from .sandbox import sandboxenv_context

py_logger = getLogger(__name__)


SAMPLE_TOTAL_PROGRESS_UNITS = 1


class SampleRunner:
    """Run a single sample (one attempt-chain) through plan + scoring.

    The retry path constructs a fresh `SampleRunner` with `retry_on_error`
    decremented and `error_retries` appended, then awaits its `run()`.
    """

    def __init__(
        self,
        *,
        task_name: str,
        log_location: str,
        create_sample_state: Callable[
            [str | None], Awaitable[tuple[Sample, TaskState]]
        ],
        sandbox: SandboxEnvironmentSpec | None,
        checkpoint: CheckpointConfig | None,
        eval_checkpoint: CheckpointConfig | None,
        resume_checkpoint: ResumeCheckpoint | None,
        max_sandboxes: int | None,
        sandbox_cleanup: bool,
        plan: Plan,
        scorers: list[Scorer] | None,
        scorer_names: list[str] | None,
        scanner: "Scanners | None",
        cleanup: Callable[[TaskState], Awaitable[None]] | None,
        generate: Generate,
        progress: Callable[[int], None],
        logger: TaskLogger | None,
        log_images: bool,
        log_model_api: bool | None,
        sample_error: SampleErrorHandler,
        sample_complete: Callable[
            [int | str, int, dict[str, SampleScore]], Awaitable[None]
        ],
        fails_on_error: bool,
        early_stopping: EarlyStopping | None,
        retry_on_error: int,
        score_on_error: bool,
        error_retries: list[EvalRetryError],
        time_limit: int | None,
        working_limit: int | None,
        semaphore: contextlib.AbstractAsyncContextManager[Any],
        eval_set_id: str | None,
        run_id: str,
        task_id: str,
        scan_id: str | None = None,
        sample_uuid: str | None = None,
    ) -> None:
        self._task_name = task_name
        self._log_location = log_location
        self._create_sample_state = create_sample_state
        self._sandbox = sandbox
        self._checkpoint = checkpoint
        self._eval_checkpoint = eval_checkpoint
        self._resume_checkpoint = resume_checkpoint
        self._max_sandboxes = max_sandboxes
        self._sandbox_cleanup = sandbox_cleanup
        self._plan = plan
        self._scorers = scorers
        self._scorer_names = scorer_names
        self._scanner = scanner
        self._cleanup = cleanup
        self._generate = generate
        self._progress = progress
        self._logger = logger
        self._log_images = log_images
        self._log_model_api = log_model_api
        self._sample_error = sample_error
        self._sample_complete = sample_complete
        self._fails_on_error = fails_on_error
        self._early_stopping = early_stopping
        self._retry_on_error = retry_on_error
        self._score_on_error = score_on_error
        self._error_retries = error_retries
        self._time_limit = time_limit
        self._working_limit = working_limit
        self._semaphore = semaphore
        self._eval_set_id = eval_set_id
        self._run_id = run_id
        self._task_id = task_id
        self._scan_id = scan_id
        self._sample_uuid = sample_uuid

        # per-run mutable state — set up inside run()
        self._sample: Sample | None = None
        self._state: TaskState | None = None
        self._sample_id: int | str | None = None
        self._error: EvalError | None = None
        self._raise_error: BaseException | None = None
        self._cancelled_error: BaseException | None = None
        self._sample_summary: EvalSampleSummary | None = None
        self._attempt_started: bool = False

    def _on_sample_event(self, event: Any) -> None:
        from inspect_ai.hooks._hooks import emit_sample_event

        # _state and _sample_id are set before _on_sample_event is wired up
        assert self._state is not None
        assert self._sample_id is not None

        if self._logger:
            self._logger.log_sample_event(self._sample_id, self._state.epoch, event)
        emit_sample_event(
            eval_set_id=self._eval_set_id,
            run_id=self._run_id,
            eval_id=self._task_id,
            sample_id=self._state.uuid,
            event=event,
        )

    def _handle_error(
        self, ex: BaseException
    ) -> tuple[EvalError, BaseException | None]:
        assert self._sample is not None
        assert self._state is not None

        sample = self._sample
        state = self._state

        def log_sample_error() -> None:
            msg = (
                f"Sample error (id: {sample.id}, epoch: {state.epoch}): "
                f"{exception_message(ex)})"
            )
            if self._retry_on_error > 0:
                msg = f"{msg}. Sample will be retried."
            elif self._score_on_error:
                msg = f"{msg}. Sample will be scored."
            py_logger.warning(msg)

        # if we have retries left then return EvalError
        if self._retry_on_error > 0:
            log_sample_error()
            return eval_error(ex, type(ex), ex, ex.__traceback__), None
        else:
            err = self._sample_error(ex)
            # with score_on_error, suppress the raise so we can score the
            # sample; error_count was still incremented on sample_error()
            # above, so the eval-level fail_on_error threshold continues
            # to apply.
            if self._score_on_error:
                log_sample_error()
                transcript()._event(ErrorEvent(error=err[0]))
                return err[0], None
            # if we aren't raising the error then print a warning
            if err[1] is None:
                log_sample_error()
            transcript()._event(ErrorEvent(error=err[0]))
            return err

    async def _emit_attempt_end(self, will_retry: bool) -> None:
        from inspect_ai.hooks._hooks import emit_sample_attempt_end

        if self._sample_summary is None or not self._attempt_started:
            return
        assert self._state is not None
        await emit_sample_attempt_end(
            self._eval_set_id,
            self._run_id,
            self._task_id,
            self._state.uuid,
            summary=self._sample_summary,
            attempt=len(self._error_retries) + 1,
            error=self._error,
            will_retry=will_retry,
        )

    async def run(self) -> dict[str, SampleScore] | EarlyStop | None:
        from inspect_ai.hooks._hooks import (
            drain_sample_events,
            emit_sample_attempt_start,
            emit_sample_end,
            emit_sample_init,
            emit_sample_scoring,
            emit_sample_start,
            start_sample_event_emitter,
        )

        # execute under sample semaphore
        async with self._semaphore:
            # materialize sample+state lazily (deferred until semaphore acquired)
            sample, state = await self._create_sample_state(self._sample_uuid)
            self._sample = sample
            self._state = state

            # validate that we have sample_id (mostly for the typechecker)
            sample_id = sample.id
            if sample_id is None:
                raise ValueError("sample must have id to run")
            self._sample_id = sample_id

            # initialise subtask and scoring context
            init_sample_model_usage()
            init_sample_role_usage()
            set_sample_state(state)
            sample_transcript = Transcript(log_model_api=self._log_model_api)
            init_transcript(sample_transcript)
            init_subtask_store(state.store)
            sample_transcript._subscribe(self._on_sample_event)
            if self._scorers:
                init_scoring_context(self._scorers, Target(sample.target))

            init_sample_assistant_internal()

            # use sandbox if provided
            sandboxenv_cm = (
                sandboxenv_context(
                    self._task_name,
                    self._sandbox,
                    self._max_sandboxes,
                    self._sandbox_cleanup,
                    sample,
                )
                if self._sandbox or sample.sandbox is not None
                else contextlib.nullcontext()
            )

            # resolve checkpoint config across all three levels with
            # precedence eval > sample > task (per-field merge — see
            # `merge_checkpoint_configs`).
            resolved_checkpoint = merge_checkpoint_configs(
                self._checkpoint, sample.checkpoint, self._eval_checkpoint
            )

            # Derive agent name for the ACP picker / TUI meta row. Mirrors
            # inspect_scout's `_agent(log)` heuristic: prefer the configured
            # eval-level solver string, fall back to the last plan step.
            agent_name: str | None = None
            if self._logger is not None and self._logger.eval.solver is not None:
                agent_name = self._logger.eval.solver
            elif self._plan.steps:
                agent_name = registry_log_name(self._plan.steps[-1])

            async with active_sample(
                task=self._task_name,
                log_location=self._log_location,
                model=str(state.model),
                sample=sample,
                epoch=state.epoch,
                message_limit=state.message_limit,
                token_limit=state.token_limit,
                cost_limit=state.cost_limit,
                time_limit=self._time_limit,
                working_limit=self._working_limit,
                fails_on_error=self._fails_on_error or (self._retry_on_error > 0),
                transcript=sample_transcript,
                checkpoint=resolved_checkpoint,
                resume_checkpoint=self._resume_checkpoint,
                eval_set_id=self._eval_set_id,
                run_id=self._run_id,
                eval_id=self._task_id,
                agent_name=agent_name,
            ) as active:
                # check for early stopping
                if self._early_stopping is not None and self._logger is not None:
                    early_stop = await self._early_stopping.schedule_sample(
                        state.sample_id, state.epoch
                    )
                    if early_stop is not None:
                        return early_stop

                start_time: float | None = None
                results: dict[str, SampleScore] = {}
                limit: EvalSampleLimit | None = None

                # begin init
                init_span = span("init", type="init")
                await init_span.__aenter__()
                cleanup_span: contextlib.AbstractAsyncContextManager[None] | None = (
                    init_span
                )

                try:
                    # sample init event (remove file bodies as they have content or absolute paths)
                    event_sample = sample.model_copy(
                        update=dict(files={k: "" for k in sample.files.keys()})
                        if sample.files
                        else None
                    )
                    transcript()._event(
                        SampleInitEvent(
                            sample=event_sample, state=state_jsonable(state)
                        )
                    )

                    # construct sample summary, used by both emit_sample_init and emit_sample_start
                    self._sample_summary = EvalSampleSummary(
                        id=sample_id,
                        epoch=state.epoch,
                        uuid=state.uuid,
                        input=sample.input,
                        choices=sample.choices,
                        target=sample.target,
                        metadata=sample.metadata or {},
                    )

                    # emit sample init before sandbox creation
                    # (only on the first attempt; not re-emitted when the sample is retried after an error)
                    if not self._error_retries:
                        await emit_sample_init(
                            self._eval_set_id,
                            self._run_id,
                            self._task_id,
                            state.uuid,
                            self._sample_summary,
                        )

                    async with sandboxenv_cm:
                        try:
                            # update active sample wth sandboxes now that we are initialised
                            # (ensure that we still exit init context in presence of sandbox error)
                            try:
                                active.sandboxes = await sandbox_connections()
                            finally:
                                await init_span.__aexit__(None, None, None)
                                cleanup_span = None

                            # record start time
                            start_time = time.monotonic()
                            init_sample_working_time(start_time)

                            # run sample w/ optional limits
                            with (
                                state._token_limit,
                                state._cost_limit,
                                state._message_limit,
                                create_time_limit(self._time_limit),
                                create_working_limit(self._working_limit),
                            ):

                                async def run(tg: TaskGroup) -> None:
                                    nonlocal limit
                                    # access to state via outer scope (via self._state too)
                                    assert self._state is not None
                                    try:
                                        # start the sample
                                        active.start(tg)

                                        # monitor working limit in the background
                                        monitor_working_limit()

                                        # start background sample event emitter
                                        start_sample_event_emitter()

                                        # set progress for plan then run it
                                        async with span("solvers"):
                                            self._state = await self._plan(
                                                self._state, self._generate
                                            )

                                    # some 'cancel' exceptions are actually user interrupts or the
                                    # result of monitor_working_limit() - for these exceptions we
                                    # want to intercept them and apply the appropriate control flow
                                    # so they can continue on and be scored.
                                    except anyio.get_cancelled_exc_class() as ex:
                                        if active.interrupt_action:
                                            # record event
                                            transcript()._event(
                                                SampleLimitEvent(
                                                    type="operator",
                                                    message="Sample completed: interrupted by operator",
                                                )
                                            )

                                            # handle the action
                                            match active.interrupt_action:
                                                case "score":
                                                    # continue to scoring (capture the most recent state)
                                                    self._state = (
                                                        sample_state() or self._state
                                                    )
                                                    limit = EvalSampleLimit(
                                                        type="operator", limit=1
                                                    )
                                                case "error":
                                                    # default error handling
                                                    (
                                                        self._error,
                                                        self._raise_error,
                                                    ) = self._handle_error(ex)

                                        elif active.limit_exceeded_error:
                                            # record event
                                            transcript()._event(
                                                SampleLimitEvent(
                                                    type="working",
                                                    message=active.limit_exceeded_error.message,
                                                    limit=active.limit_exceeded_error.limit,
                                                )
                                            )

                                            # capture most recent state for scoring
                                            self._state = sample_state() or self._state
                                            limit = EvalSampleLimit(
                                                type=active.limit_exceeded_error.type,
                                                limit=active.limit_exceeded_error.limit
                                                if active.limit_exceeded_error.limit
                                                is not None
                                                else -1,
                                            )

                                        # this was not a user interrupt or working time limit so propagate
                                        else:
                                            raise
                                    finally:
                                        # ensures that monitor_working_limit() and any coroutines
                                        # created w/ background() are cancelled
                                        tg.cancel_scope.cancel()

                                try:
                                    # emit/log sample start
                                    if self._logger is not None:
                                        await self._logger.start_sample(
                                            self._sample_summary
                                        )

                                    # only emit the sample start once: not on retries
                                    if not self._error_retries:
                                        await emit_sample_start(
                                            self._eval_set_id,
                                            self._run_id,
                                            self._task_id,
                                            state.uuid,
                                            self._sample_summary,
                                        )

                                    await emit_sample_attempt_start(
                                        self._eval_set_id,
                                        self._run_id,
                                        self._task_id,
                                        state.uuid,
                                        self._sample_summary,
                                        attempt=len(self._error_retries) + 1,
                                    )
                                    self._attempt_started = True

                                    async with anyio.create_task_group() as tg:
                                        tg.start_soon(run, tg)
                                except Exception as ex:
                                    raise inner_exception(ex)
                                finally:
                                    # capture sample limits
                                    record_sample_limit_data(
                                        len((sample_state() or self._state).messages)
                                    )

                        except SandboxTimeoutError as ex:
                            raise RuntimeError(str(ex)) from ex

                        except TimeoutError:
                            # Scoped time limits manifest themselves as LimitExceededError, not
                            # TimeoutError.
                            py_logger.warning(
                                "Unexpected timeout error reached top of sample stack. Are you handling TimeoutError when applying timeouts?"
                            )

                            # capture most recent state for scoring
                            self._state = sample_state() or self._state

                        except LimitExceededError as ex:
                            # capture most recent state for scoring
                            self._state = sample_state() or self._state
                            limit = EvalSampleLimit(
                                type=ex.type,
                                limit=ex.limit if ex.limit is not None else -1,
                            )

                        except TerminateSampleError as ex:
                            # emit event
                            transcript()._event(
                                SampleLimitEvent(
                                    type="operator", limit=1, message=ex.reason
                                )
                            )

                            # capture most recent state for scoring
                            self._state = sample_state() or self._state
                            limit = EvalSampleLimit(type="operator", limit=1)

                        except anyio.get_cancelled_exc_class() as ex:
                            with anyio.CancelScope(shield=True):
                                self._cancelled_error = ex
                                # convert to standard error
                                self._error = eval_error(
                                    ex, type(ex), ex, ex.__traceback__
                                )
                                transcript()._event(ErrorEvent(error=self._error))

                        except Exception as ex:
                            self._error, self._raise_error = self._handle_error(ex)

                        # mark completed
                        assert self._state is not None
                        self._state.completed = True

                        # set timeout for scoring. if the original timeout was hit we still
                        # want to provide opportunity for scoring, but we don't necessarily
                        # want to wait the full timeout again (especially in the case where
                        # the cause of the timeout is a hung container and scoring requires
                        # interacting with the container). as a middle ground we use half
                        # of the original timeout value for scoring.
                        scoring_time_limit = (
                            self._time_limit / 2 if self._time_limit else None
                        )

                        set_sample_state(self._state)
                        if self._state.scores is None:
                            self._state.scores = {}
                        solver_score_names = [*self._state.scores]

                        # scoring
                        with anyio.CancelScope(
                            shield=self._cancelled_error is not None
                        ):
                            await emit_sample_scoring(
                                self._eval_set_id,
                                self._run_id,
                                self._task_id,
                                self._state.uuid,
                            )
                            try:
                                # timeout during scoring will result in an ordinary sample error
                                with create_time_limit(scoring_time_limit):
                                    # score on success, or when score_on_error is on
                                    # for the final attempt (no retries left, not cancelled)
                                    if self._error is None or (
                                        self._score_on_error
                                        and self._retry_on_error == 0
                                        and self._cancelled_error is None
                                    ):
                                        async with span(name="scorers"):
                                            for scorer_idx, scorer in enumerate(
                                                self._scorers or []
                                            ):
                                                scorer_name = (
                                                    self._scorer_names[scorer_idx]
                                                    if self._scorer_names
                                                    else unique_scorer_name(
                                                        scorer,
                                                        list(
                                                            {
                                                                *solver_score_names,
                                                                *results,
                                                            }
                                                        ),
                                                    )
                                                )
                                                async with span(
                                                    name=scorer_name, type="scorer"
                                                ):
                                                    if not scorer:
                                                        continue
                                                    score_result = await scorer(
                                                        self._state,
                                                        Target(sample.target),
                                                    )
                                                    if (
                                                        scorer_name
                                                        in self._state.scores
                                                    ):
                                                        raise RuntimeError(
                                                            f"Scorer {scorer_name} has modified state.scores"
                                                        )
                                                    if score_result is not None:
                                                        self._state.scores[
                                                            scorer_name
                                                        ] = score_result

                                                        transcript()._event(
                                                            ScoreEvent(
                                                                score=score_result,
                                                                target=sample.target,
                                                                scorer=scorer_name,
                                                                scorer_args=registry_params(
                                                                    scorer
                                                                )
                                                                if has_registry_params(
                                                                    scorer
                                                                )
                                                                else None,
                                                                model_usage=sample_model_usage()
                                                                or None,
                                                                role_usage=sample_role_usage()
                                                                or None,
                                                            )
                                                        )

                                                        results[scorer_name] = (
                                                            SampleScore(
                                                                score=score_result,
                                                                sample_id=sample.id,
                                                                sample_metadata=sample.metadata,
                                                                scorer=registry_unqualified_name(
                                                                    scorer
                                                                ),
                                                            )
                                                        )

                                    for name in solver_score_names:
                                        score = self._state.scores[name]
                                        transcript()._event(
                                            ScoreEvent(
                                                score=score,
                                                target=sample.target,
                                                scorer=name,
                                                model_usage=sample_model_usage()
                                                or None,
                                                role_usage=sample_role_usage() or None,
                                            )
                                        )
                                        results[name] = SampleScore(
                                            score=score,
                                            sample_id=self._state.sample_id,
                                            sample_metadata=self._state.metadata,
                                        )

                            except anyio.get_cancelled_exc_class() as ex:
                                with anyio.CancelScope(shield=True):
                                    self._cancelled_error = ex
                                    if active.interrupt_action:
                                        transcript()._event(
                                            SampleLimitEvent(
                                                type="operator",
                                                message="Unable to score sample due to operator interruption",
                                            )
                                        )

                                    # convert to standard error
                                    self._error = eval_error(
                                        ex, type(ex), ex, ex.__traceback__
                                    )
                                    transcript()._event(ErrorEvent(error=self._error))

                            except Exception as ex:
                                if active.interrupt_action is not None:
                                    # Operator-interrupted: log to transcript but
                                    # don't propagate to error/retry. The operator
                                    # EvalSampleLimit is set in the run() handler.
                                    scorer_error = eval_error(
                                        ex, type(ex), ex, ex.__traceback__
                                    )
                                    transcript()._event(ErrorEvent(error=scorer_error))
                                else:
                                    self._error, self._raise_error = self._handle_error(
                                        ex
                                    )
                            finally:
                                # run task cleanup if required (inside sandbox context)
                                if self._cleanup is not None:
                                    with anyio.CancelScope(shield=True):
                                        try:
                                            await self._cleanup(self._state)
                                        except Exception as ex:
                                            py_logger.warning(
                                                f"Exception occurred during task cleanup: {ex}",
                                                exc_info=ex,
                                            )

                except Exception as ex:
                    self._error, self._raise_error = self._handle_error(ex)
                finally:
                    # cleanup the task init span if required
                    if cleanup_span is not None:
                        with anyio.CancelScope(
                            shield=self._cancelled_error is not None
                        ):
                            await cleanup_span.__aexit__(None, None, None)

                # complete the sample if there is no error or if there is no retry_on_error in play
                with anyio.CancelScope(shield=self._cancelled_error is not None):
                    # drain sample events for both completion and retry paths
                    await drain_sample_events()

                    if (
                        not self._error
                        or (self._retry_on_error == 0)
                        or (self._cancelled_error is not None)
                    ):
                        self._progress(SAMPLE_TOTAL_PROGRESS_UNITS)

                        assert self._state is not None
                        sample = self._sample
                        state = self._state

                        # if we are logging images then be sure to base64 images injected by solvers
                        if self._log_images:
                            state = (await states_with_base64_content([state]))[0]

                        # otherwise ensure there are no base64 images in sample or messages
                        else:
                            sample = sample_without_base64_content(sample)
                            state = state_without_base64_content(state)

                        # publish back so post-loop branches see the cleaned versions
                        self._sample = sample
                        self._state = state

                        # emit/log sample end
                        def make_eval_sample(
                            include_events: bool = True,
                        ) -> EvalSample:
                            return create_eval_sample(
                                start_time=start_time,
                                sample=sample,
                                state=state,
                                scores=results,
                                error=self._error,
                                limit=limit,
                                error_retries=self._error_retries,
                                started_at=sample_start_datetime(),
                                include_events=include_events,
                            )

                        if self._logger:
                            eval_sample = await log_sample(
                                eval_sample=make_eval_sample(
                                    include_events=self._logger.buffer_db is None
                                ),
                                logger=self._logger,
                                log_images=self._log_images,
                            )
                        else:
                            eval_sample = make_eval_sample()
                        # Call via module attribute so tests can monkey-patch
                        # `inspect_ai._eval.task.scan.scan_eval_sample` to
                        # inject crash/error behaviour. See e.g.
                        # tests/test_eval_set_scanner.py::
                        # test_eval_set_resume_scans_when_intermediate_run_crashed_after_clean_finalize
                        # — a `from .scan import scan_eval_sample` here would
                        # bind the symbol at import time and bypass the patch.
                        await _scan_mod.scan_eval_sample(
                            eval_sample,
                            self._scanner,
                            scan_id=self._scan_id,
                            eval_id=self._task_id,
                            log_location=self._log_location,
                            model=str(state.model),
                            eval_spec=self._logger.eval if self._logger else None,
                        )
                        await self._emit_attempt_end(will_retry=False)
                        await emit_sample_end(
                            self._eval_set_id,
                            self._run_id,
                            self._task_id,
                            state.uuid,
                            eval_sample,
                        )

        # error that should be retried (we do this outside of the above scope so that we can
        # retry outside of the original semaphore -- our retry will therefore go to the back
        # of the sample queue)
        if (
            self._error
            and self._retry_on_error > 0
            and self._cancelled_error is None
            and active.interrupt_action is None
        ):
            await self._emit_attempt_end(will_retry=True)

            assert self._state is not None

            # remove any buffered sample events
            if self._logger is not None:
                self._logger.remove_sample(self._state.sample_id, self._state.epoch)

            # recurse w/ tick down of retry_on_error and append of error to error_retries
            return await SampleRunner(
                task_name=self._task_name,
                log_location=self._log_location,
                create_sample_state=self._create_sample_state,
                sandbox=self._sandbox,
                checkpoint=self._checkpoint,
                eval_checkpoint=self._eval_checkpoint,
                resume_checkpoint=self._resume_checkpoint,
                max_sandboxes=self._max_sandboxes,
                sandbox_cleanup=self._sandbox_cleanup,
                plan=self._plan,
                scorers=self._scorers,
                scorer_names=self._scorer_names,
                scanner=self._scanner,
                cleanup=self._cleanup,
                generate=self._generate,
                progress=self._progress,
                logger=self._logger,
                log_images=self._log_images,
                log_model_api=self._log_model_api,
                sample_error=self._sample_error,
                sample_complete=self._sample_complete,
                early_stopping=self._early_stopping,
                fails_on_error=self._fails_on_error,
                # tick retry count down
                retry_on_error=self._retry_on_error - 1,
                score_on_error=self._score_on_error,
                # forward on error that caused retry
                error_retries=[*self._error_retries, eval_retry_error(self._error)],
                time_limit=self._time_limit,
                working_limit=self._working_limit,
                semaphore=self._semaphore,
                eval_set_id=self._eval_set_id,
                run_id=self._run_id,
                task_id=self._task_id,
                scan_id=self._scan_id,
                sample_uuid=self._state.uuid,
            ).run()

        # re-raise cancellation after logging to preserve structured concurrency
        elif self._cancelled_error is not None:
            raise self._cancelled_error

        # no error
        elif self._error is None:
            # call sample_complete callback if we have score results
            assert self._state is not None
            if results is not None:
                await self._sample_complete(
                    self._state.sample_id, self._state.epoch, results
                )
            return results

        # we have an error and should raise it
        elif self._raise_error is not None:
            raise self._raise_error

        # we have an error and should not raise it
        else:
            return None
