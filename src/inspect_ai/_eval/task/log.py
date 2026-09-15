import logging
from datetime import datetime
from importlib import metadata as importlib_metadata
from importlib.metadata import Distribution
from typing import TYPE_CHECKING, Any, cast

import anyio
from shortuuid import uuid

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._eval.task.util import slice_dataset
from inspect_ai._util.background import run_in_background
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.dateutil import datetime_now_utc, iso_now
from inspect_ai._util.error import is_cancellation_message
from inspect_ai._util.git import git_context, redact_url_credentials
from inspect_ai._util.package import (
    get_distribution_direct_url,
    get_distribution_for_object,
)
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import (
    registry_log_name,
    registry_lookup,
    registry_params,
)
from inspect_ai.dataset import Dataset
from inspect_ai.event._event import Event
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalError,
    EvalPlan,
    EvalPlanStep,
    EvalResults,
    EvalRevision,
    EvalSample,
    EvalSpec,
    EvalStats,
    EvalStatus,
    HeadlineMetric,
)
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalScorer,
    eval_config_defaults,
)
from inspect_ai.log._recorders import Recorder
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover._api import sample_record_time
from inspect_ai.model import (
    GenerateConfig,
    Model,
    ModelName,
)
from inspect_ai.model._model import model_usage, role_usage
from inspect_ai.model._model_config import (
    model_args_for_log,
    model_roles_to_model_roles_config,
)
from inspect_ai.scorer._metric import MetricSpec
from inspect_ai.scorer._scorer import ScorerSpec
from inspect_ai.solver._constants import SOLVER_ALL_PARAMS_ATTR
from inspect_ai.solver._plan import Plan
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.viewer import ViewerConfig

logger = logging.getLogger(__name__)

_STALE_FLUSH_INTERVAL: float = 60

# how many seeded prior records the reuse sweep reads back from the recorder
# at once (see TaskLogger.read_prior_sample)
_PRIOR_READ_CONCURRENCY = 4

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import BufferConfig
    from inspect_ai.log._config_update import ConfigUpdate
    from inspect_ai.log._recorders.buffer.history import SampleHistory
    from inspect_ai.log._transcript import TranscriptHistoryProvider


def resolve_revision() -> EvalRevision | None:
    git = git_context()
    return (
        EvalRevision(type="git", origin=git.origin, commit=git.commit, dirty=git.dirty)
        if git
        else None
    )


def resolve_task_distribution(task_registry_name: str | None) -> Distribution | None:
    """The installed distribution that provides an external task.

    Resolves the actual *distribution* (e.g. ``harder-tasks-judge-run``) that
    ships the task — even when the task belongs to a namespace package whose
    import name (e.g. ``harder_tasks``) is not itself a distribution. Returns
    None for builtin tasks, local-file tasks, and tasks not installed from a
    package.
    """
    if task_registry_name is None:
        return None
    task = registry_lookup("task", task_registry_name)
    if task is None:
        return None
    distribution = get_distribution_for_object(task)
    if distribution is None:
        return None
    # exclude inspect_ai itself (builtin tasks)
    if distribution.name.replace("-", "_").lower() == PKG_NAME:
        return None
    return distribution


def resolve_package_revision(distribution: Distribution | None) -> EvalRevision | None:
    """Resolve the git revision of a task's installed distribution.

    Reads PEP 610 ``direct_url.json`` so tasks installed from a git URL record
    the exact commit that was checked out, even when the eval process has no
    local git working tree (the common case for remotely-executed tasks). The
    returned revision omits ``dirty`` — an installed package has no working tree
    to be dirty.
    """
    if distribution is None:
        return None
    direct_url = get_distribution_direct_url(distribution)
    if (
        direct_url is None
        or direct_url.vcs_info is None
        or direct_url.vcs_info.vcs != "git"
    ):
        return None
    return EvalRevision(
        type="git",
        # direct_url.json can carry embedded credentials when the package was
        # installed from an authenticated git URL; redact them as git_context()
        # does so tokens never reach the eval log.
        origin=redact_url_credentials(direct_url.url.removeprefix("git+")),
        commit=direct_url.vcs_info.commit_id,
    )


def _is_high_throughput(sample_count: int) -> bool:
    """Detect high-throughput runs that benefit from reduced logging overhead."""
    return sample_count >= 1000


def _warn_if_clock_behind_prior(
    seeded: list[EvalSampleSummary], prior: "str | list[EvalSample]"
) -> None:
    """Warn when this clock reads earlier than the prior attempt's latest record.

    Crash recovery decides between an inherited record and this attempt's
    buffered re-run of it by timestamp (``_recover._api._superseded_by_buffer``):
    the re-run started after the inherited record ended. A clock behind
    the prior attempt's by more than the gap between its finish and this start
    would invert that. Only a lower bound on the skew is observable here, so
    there is nothing to repair; the warning names the hazard.
    """
    latest: datetime | None = None
    for summary in seeded:
        ended = sample_record_time(summary)
        if ended is not None and (latest is None or ended > latest):
            latest = ended
    if latest is not None and datetime_now_utc() < latest:
        logger.warning(
            f"The prior log {prior if isinstance(prior, str) else ''} has a sample "
            f"record from {latest.isoformat()}, later than this clock's "
            f"current time: the clock runs behind the prior attempt's, so crash "
            "recovery of this attempt may prefer inherited samples over its own "
            "re-runs of them."
        )


def _seeded_key(id: str | int, epoch: int) -> SampleRecordKey:
    """The ``_seeded_pending`` key for a sample: its id in string form.

    The recorder names a sample's record by ``f"{id}_epoch_{epoch}"``, so an
    int-id sample answers to its string id too; the pending set must match
    the same way or a control request's string id bypasses the guard.
    """
    return SampleRecordKey(str(id), epoch)


class TaskLogger:
    def __init__(
        self,
        task_name: str,
        task_version: int | str,
        task_file: str | None,
        task_registry_name: str | None,
        task_display_name: str | None,
        task_id: str | None,
        eval_set_id: str | None,
        run_id: str,
        solver: SolverSpec | None,
        tags: list[str] | None,
        model: Model,
        model_roles: dict[str, Model | list[Model]] | None,
        dataset: Dataset,
        scorer: list[ScorerSpec] | None,
        metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
        | dict[str, list[MetricSpec]]
        | None,
        headline_metric: HeadlineMetric | None,
        sandbox: SandboxEnvironmentSpec | None,
        task_attribs: dict[str, Any],
        task_args: dict[str, Any],
        task_args_passed: dict[str, Any],
        model_args: dict[str, Any],
        eval_config: EvalConfig,
        metadata: dict[str, Any] | None,
        viewer: ViewerConfig | None,
        recorder: Recorder,
        header_only: bool,
        dynamic_dataset: bool = False,
    ) -> None:
        packages = {
            PKG_NAME: importlib_metadata.version(PKG_NAME),
        }
        task_distribution = resolve_task_distribution(task_registry_name)
        revision = resolve_package_revision(task_distribution) or resolve_revision()
        if task_distribution is not None:
            packages[task_distribution.name] = task_distribution.version

        # redact authentication oriented model_args
        model_args = model_args_for_log(model_args)

        # cwd_relative_path for sandbox config
        if sandbox and isinstance(sandbox.config, str):
            sandbox = SandboxEnvironmentSpec(
                sandbox.type, cwd_relative_path(sandbox.config)
            )

        # ensure that the dataset has sample ids and record them
        sample_ids = cast(
            list[int | str],
            [
                sample.id
                for sample in slice_dataset(
                    dataset,
                    eval_config.limit,
                    eval_config.sample_id,
                    dynamic=dynamic_dataset,
                )
            ],
        )

        # total samples accounting for slicing and epochs
        epochs = eval_config.epochs if eval_config.epochs else 1
        total_samples = len(sample_ids) * epochs

        # high-throughput runs still get a larger flush buffer (fewer main
        # eval-log flushes), but we no longer force `log_realtime` or
        # `score_display` off. Realtime logging is now cheap: sample completion
        # logs directly from resident memory instead of reading every event
        # back out of the buffer DB (see `log_sample` in run.py), and the
        # WAL/persistent-connection buffer DB removed the read/write contention
        # that motivated disabling it (#3173). Score-display recompute is
        # throttled and was measured to be negligible at high sample counts.
        high_throughput = _is_high_throughput(total_samples)

        # write defaults for unspecified config
        for name, value in eval_config_defaults().items():
            if getattr(eval_config, name, None) is None:
                setattr(eval_config, name, value)

        # resolve scorers
        eval_scorers = resolve_eval_scorers(scorer)

        # resolve metrics
        eval_metrics = resolve_eval_metrics(metrics)

        # create eval spec
        self.eval = EvalSpec(
            eval_set_id=eval_set_id,
            run_id=run_id,
            created=iso_now(),
            task=f"{task_name}",
            task_id=task_id if task_id else uuid(),
            task_version=task_version,
            task_file=task_file,
            task_registry_name=task_registry_name,
            task_display_name=task_display_name,
            task_attribs=task_attribs,
            task_args=task_args,
            task_args_passed=task_args_passed,
            solver=solver.solver if solver else None,
            tags=tags,
            solver_args=solver.args if solver else None,
            solver_args_passed=solver.args_passed if solver else None,
            model=f"{ModelName(model).api}/{model.name}",
            model_generate_config=model.config,
            model_base_url=model.explicit_base_url,
            model_roles=model_roles_to_model_roles_config(model_roles),
            dataset=EvalDataset(
                name=dataset.name,
                location=cwd_relative_path(dataset.location),
                samples=len(dataset),
                sample_ids=sample_ids,
                shuffled=dataset.shuffled,
            ),
            scorers=eval_scorers,
            metrics=eval_metrics,
            headline_metric=headline_metric,
            sandbox=sandbox,
            model_args=model_args,
            config=eval_config,
            revision=revision,
            packages=packages,
            metadata=metadata,
            viewer=viewer,
        )

        # stack recorder and location
        self.recorder = recorder
        self.header_only = header_only

        # number of samples logged without error / distinct samples logged
        # (cancellation-resolved ones tracked separately — see samples_logged)
        self._samples_completed = 0
        self._logged_sample_keys: set[tuple[str | int, int]] = set()
        self._cancelled_sample_keys: set[tuple[str | int, int]] = set()

        # size of flush buffer (how many samples we buffer before hitting storage)
        self.flush_buffer = eval_config.log_buffer or recorder.default_log_buffer(
            total_samples, high_throughput
        )
        if high_throughput and eval_config.log_buffer is None:
            eval_config.log_buffer = self.flush_buffer
        self.flush_pending: list[tuple[str | int, int]] = []
        self._init_stale_flush_state()

        # set once log_finish() has finalized and torn down the recorder. The
        # flush/buffer directive providers stay attached to this eval's
        # EvalState under --ctl-server=keep (finished evals remain visible), so
        # they must read as a finished no-op rather than reaching into the
        # torn-down recorder.
        self._finished = False

        # set once a retry attempt's log has been seeded with the prior
        # attempt's sample records (see seed_from_prior); the limit bounds the
        # sweep's read-back of those records (see read_prior_sample)
        self._prior_seeded = False
        self._prior_read_limit = anyio.Semaphore(_PRIOR_READ_CONCURRENCY)
        # seeded (id, epoch) keys the reuse sweep has not yet resolved: the
        # records sample_summaries withholds from the control channel (see
        # its docstring). A key leaves when the sweep accepts its record
        # (note_reused_sample) or a completion for it lands. Keyed by
        # _seeded_key (id as str): the control channel supplies string ids,
        # and the recorder resolves them against a sample's string form, so
        # a dataset-typed int key would let "2" read the withheld record 2.
        self._seeded_pending: set[SampleRecordKey] = set()

        # sample buffer db
        self._buffer_db: SampleBufferDatabase | None = None

        # how many of the run's process-scoped ctl config updates this log
        # has recorded (see record_inherited_config_updates)
        self._process_updates_recorded = 0

    def _init_stale_flush_state(self) -> None:
        # `_flush_lock` serializes every path that writes the log via the
        # recorder — the buffer-full flush and the stale-flush timer (both
        # through `_flush_pending_samples`), the on-demand `flush_samples()`
        # (control channel), and the teardown in `log_finish()` — so they can't
        # race the recorder or each other's bookkeeping (the recorder has its
        # own lock, so the writes themselves are already safe; this keeps the
        # flushed count accurate and stops an on-demand flush from touching the
        # recorder after log_finish has torn it down). `_flush_pending_lock`
        # guards the `flush_pending` list itself (a short, await-free section).
        self._flush_lock = anyio.Lock()
        self._flush_pending_lock = anyio.Lock()
        self._stale_flush_cancel_scope: anyio.CancelScope | None = None
        self._stale_flush_stops: set[anyio.Event] = set()
        self._stale_flush_generation = 0
        self._stale_flush_interval = _STALE_FLUSH_INTERVAL
        self._discarded = False

    async def init(self) -> None:
        self._bump_created_past_existing_logs()
        self._location = await self.recorder.log_init(self.eval)

        # process-scoped ctl retunes applied earlier in this run (before a
        # retry attempt or a later eval-set child started) still govern this
        # fresh log's eval — snapshot them so the log records the overrides
        # it runs under (marked inherited via provenance.metadata)
        await self.record_inherited_config_updates()

        if self.eval.config.log_realtime is False:
            return

        self._buffer_db = SampleBufferDatabase(
            location=self._location,
            log_images=self.eval.config.log_images is not False,
            log_shared=self.eval.config.log_shared,
        )

    async def reinit(self) -> None:
        """Reset this logger for a retry attempt with a fresh eval entry."""
        from inspect_ai._control.eval_state import detach_eval_live

        # the superseded attempt's EvalState holds providers bound to THIS
        # logger, which is about to be re-pointed at the new attempt
        detach_eval_live(self.eval.eval_id)

        if self._finished:
            await self._stop_stale_flush_timer()
        else:
            # the attempt failed before finishing its log (its prior-log seed
            # or a log write failed): log_finish never released its recorder
            # entry (open temp zip) or buffer db, so release them before the
            # eval_id moves on. A destination its flushes did write stays: it
            # holds the seeded prior set plus this attempt's flushed
            # completions, and the dispatcher makes it the retry's source
            await self.discard(keep_destination=True)
        self.eval = self.eval.model_copy(update=dict(eval_id=uuid(), created=iso_now()))
        self._samples_completed = 0
        self._logged_sample_keys = set()
        self._cancelled_sample_keys = set()
        self.flush_pending = []
        self._finished = False
        self._discarded = False
        # the retry attempt re-enters task_run, which seeds its fresh log
        self._prior_seeded = False
        self._seeded_pending = set()
        # the retry attempt gets a fresh log, which must re-record the run's
        # full accumulated process-scoped updates in init() below
        self._process_updates_recorded = 0
        # log_finish() (or discard() above) has cleaned up the buffer db; a
        # stale one would collide with the new attempt's (the location repeats
        # if `created` lands on the same second)
        await self._release_buffer_db(keep=False)
        await self.init()

    def _bump_created_past_existing_logs(self) -> None:
        """Bump `eval.created` past any existing log at the would-be path.

        File recorders compute the log filename from `eval.created` (down
        to a second), `task`, `task_id`, and `model`. Two logs that share
        all of those collide on the filesystem; we walk `created` forward
        until the computed path doesn't already exist.
        """
        log_file_path = getattr(self.recorder, "_log_file_path", None)
        if log_file_path is None:
            return
        from datetime import datetime, timedelta, timezone

        from inspect_ai._util.file import filesystem

        max_attempts = 60
        for _ in range(max_attempts):
            path = log_file_path(self.eval)
            if not filesystem(path).exists(path):
                return
            dt = datetime.fromisoformat(self.eval.created) + timedelta(seconds=1)
            bumped = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
            self.eval = self.eval.model_copy(update=dict(created=bumped))
        raise RuntimeError(
            f"Could not find a unique log filename for task {self.eval.task!r} "
            f"(task_id={self.eval.task_id}) after {max_attempts} attempts; "
            f"last tried {log_file_path(self.eval)!r}."
        )

    @property
    def location(self) -> str:
        return self._location

    @property
    def samples_completed(self) -> int:
        return self._samples_completed

    @property
    def samples_logged(self) -> int:
        """Samples this attempt's log holds a genuine resolution for.

        Unlike :attr:`samples_completed` this counts errored and retry-reused
        samples too, as *distinct* ``(id, epoch)`` keys: a re-log of the same
        sample (a requeued sample's re-run superseding its errored record)
        replaces the log entry rather than adding one, so it must not
        inflate the count. Cancellation-resolved samples (an operator
        ``sample cancel``, or a drain landing while the sample was still
        materializing) are *excluded* even though their transcripts are in
        the log: a cancellation is not a resolution anywhere else in the
        system (``eval-retry`` re-runs them, retry seeding skips them), and
        counting them would let a drained log read complete while its
        never-ran samples silently drop from a later ``inspect eval-set``
        re-invocation. Consumed at finalize when a graceful cancel/drain
        abandoned queued samples, so eval-set's run-vs-reuse completeness
        check can see that the log holds fewer samples than planned (see
        ``design/ctl/task-drain.md``).
        """
        return len(self._logged_sample_keys) - len(self._cancelled_sample_keys)

    @property
    def buffer_db(self) -> SampleBufferDatabase | None:
        return self._buffer_db

    @property
    def prior_seeded(self) -> bool:
        """Whether this attempt's log was seeded from a prior attempt's samples."""
        return self._prior_seeded

    @property
    def destination_written(self) -> bool:
        """Whether anything has reached this attempt's destination log file.

        A finished log was written by definition (``log_finish`` sets
        ``_finished`` only after the recorder's final flush succeeded, and
        the recorder stops tracking the eval at that point). Otherwise the
        recorder reports whether any flush has landed.
        """
        if self._finished:
            return True
        return self.recorder.destination_written(self.eval)

    @property
    def finished(self) -> bool:
        """Whether :meth:`log_finish` completed for this attempt (its log is written)."""
        return self._finished

    async def seed_from_prior(
        self,
        prior: "str | list[EvalSample]",
        keep: set[tuple[str | int, int]] | None,
    ) -> None:
        """Seed this retry attempt's log with the prior attempt's sample records.

        Called by ``task_run`` after ``init`` and before ``log_start`` when the
        attempt has an eligible sample source (see ``EvalSampleSource.seed``).
        ``prior`` is the prior log's location or an in-memory prior log's
        samples; the recorder copies a same-format prior log file whole and
        re-logs samples otherwise (see ``Recorder.log_seed``). Restricted to
        the planned ``keep`` keys. With no upfront plan, sample ID and epoch
        filters still restrict the seed, including samples produced later by
        a dynamic feed. A limited dynamic feed supplies its initial plan and
        calls :meth:`seed_added_samples` as it admits further samples.

        Afterwards the log holds every prior record in the upfront selection,
        so whatever ends the attempt, ``log_finish`` preserves those records.
        Limited dynamic feeds extend that guarantee when each admission copy
        finishes; cancellation during admission preserves only copies made
        so far.
        Seeded records are *not* counted as this attempt's resolutions here:
        :attr:`samples_logged` and :attr:`samples_completed` count a reused
        record when the reuse sweep accepts it (:meth:`note_reused_sample`)
        and a re-run when it completes, so a graceful drain that abandons a
        seeded errored sample's re-run still reads that sample as unresolved
        (its only record is the prior attempt's error) and a later eval-set
        pass re-runs it.

        A prior log that no longer exists leaves the attempt unseeded with a
        warning (every planned sample runs fresh, as the reuse sweep's own
        lookup degrades for a missing log). Any other read failure — after
        the recorder's own retries — raises; the caller fails the attempt
        without writing a log.
        """
        try:
            if keep is None:
                # a dynamic feed has no upfront plan: seed every prior record
                # within the explicit sample-id filter and the epoch count
                from .util import sample_id_filter

                source = await self.recorder.seed_source(self.eval, prior)
                matcher = (
                    sample_id_filter(self.eval.config.sample_id)
                    if self.eval.config.sample_id is not None
                    else None
                )
                keep = {
                    (id, epoch)
                    for id, epoch in source.keys
                    if (matcher is None or matcher.matches(id))
                    and epoch <= (self.eval.config.epochs or 1)
                }
            await self.recorder.log_seed(self.eval, prior, keep)
        except FileNotFoundError:
            logger.warning(
                f"Prior log {prior} not found: retry attempt will re-run every "
                "sample rather than reusing the prior attempt's."
            )
            return
        self._prior_seeded = True
        seeded = await self.recorder.sample_summaries(self.eval)
        self._seeded_pending = {_seeded_key(s.id, s.epoch) for s in seeded or []}
        _warn_if_clock_behind_prior(seeded or [], prior)

    async def seed_added_samples(
        self, prior: "str | list[EvalSample]", keep: set[tuple[str | int, int]]
    ) -> None:
        """Carry admitted dynamic samples into a limited retry before dispatch.

        Their selection is unknown at startup. Copying them only after the
        feed applies its limit prevents excluded transcripts from reaching
        any destination flush, while retaining prior results and errors for
        every admitted sample. Each record is withheld from live readers as
        it lands (``on_sample``), like the initial seed's.
        """
        await self.recorder.log_seed_samples(
            self.eval,
            prior,
            keep,
            on_sample=lambda id, epoch: self._seeded_pending.add(
                _seeded_key(id, epoch)
            ),
        )

    async def read_prior_sample(self, id: str | int, epoch: int) -> EvalSample | None:
        """The seeded prior record for ``(id, epoch)``, read from the recorder, or None.

        The reuse sweep's lookup once the log is seeded: served from the
        recorder's local copy (no destination read, so an absent key costs
        nothing remote). Every planned sample's ``run_sample`` calls this at
        attempt start, so the reads are bounded by ``_prior_read_limit``:
        the recorder serializes them on its own lock, and without the bound
        every other lock user (a control-channel listing, a live completion)
        would queue behind the whole sweep. The key matches in string form,
        as the recorder names a sample's record (``1`` and ``"1"`` are the
        same record; ``"001"`` is another) — the rule the ``.eval`` reader
        has always applied.
        """
        async with self._prior_read_limit:
            return await self.recorder.buffered_sample(self.eval, id, epoch)

    def note_reused_sample(self, sample: EvalSample) -> None:
        """Record that the reuse sweep accepted a seeded prior sample as this attempt's result.

        The bookkeeping half of :meth:`complete_sample` for a record the
        seed already put in the log: nothing is written or flushed.
        """
        self._record_sample_outcome(sample)

    async def log_start(self, plan: EvalPlan) -> None:
        await self.recorder.log_start(self.eval, plan)
        # the first destination write: for a seeded retry attempt it already
        # carries the complete prior sample set
        await self.recorder.flush(self.eval)

    async def start_sample(self, sample: EvalSampleSummary) -> None:
        if self._buffer_db is not None:
            self._buffer_db.start_sample(sample)

    def log_sample_event(self, id: str | int, epoch: int, event: Event) -> None:
        # log the sample event
        if self._buffer_db is not None:
            self._buffer_db.log_events([SampleEvent(id=id, epoch=epoch, event=event)])

    def remove_sample(self, id: str | int, epoch: int) -> None:
        if self._buffer_db is not None:
            self._buffer_db.remove_samples([(id, epoch)])

    async def sample_summaries(self) -> list[EvalSampleSummary] | None:
        """Live completed-sample summaries (handed to the control channel via ``register_eval``).

        Withholds the seeded prior records the reuse sweep has not yet
        resolved (``_seeded_pending``). Until the sweep accepts one as this
        attempt's result or its re-run completes, it is the prior attempt's
        record rather than an outcome of this attempt: listed, it would hide
        the re-run's running row or render a sample still awaiting its
        re-run as the prior's error. Withheld, the sample reads running or
        pending exactly as it did before logs were seeded.
        """
        summaries = await self.recorder.sample_summaries(self.eval)
        if summaries is None or not self._seeded_pending:
            return summaries
        return [
            s
            for s in summaries
            if _seeded_key(s.id, s.epoch) not in self._seeded_pending
        ]

    async def read_sample(
        self,
        id: str | int,
        epoch: int,
        *,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample | None:
        """Read one full sample (recorder buffer, then on-disk log), or None.

        Withholds an unresolved seeded prior record exactly as
        :meth:`sample_summaries` does: the per-sample directives (requeue,
        cancel, error detail) resolve a sample's state from this read, and a
        seeded record served here would make a sample that has not yet run
        look terminal — accepting a requeue that then runs it twice, or
        answering a cancel with "already finished". The reuse sweep reads
        seeded records through :meth:`read_prior_sample` instead.
        """
        # The whole-sample counterpart to `sample_summaries`, handed to the
        # control channel via `register_eval` so per-sample reads (error detail,
        # event pages) source from the *same* place the samples listing does.
        # Prefer the recorder's not-yet-flushed in-memory sample, falling back
        # to the finalized on-disk log once it's flushed / the recorder is torn
        # down — otherwise those reads see only the on-disk log and miss a
        # just-completed (or reused-on-retry) sample the listing already shows.
        if _seeded_key(id, epoch) in self._seeded_pending:
            return None
        sample = await self.recorder.buffered_sample(
            self.eval, id, epoch, exclude_fields=exclude_fields
        )
        if sample is None:
            from inspect_ai.log._file import read_eval_log_sample_async

            try:
                sample = await read_eval_log_sample_async(
                    self.location, id, epoch, exclude_fields=exclude_fields
                )
            except (IndexError, FileNotFoundError):
                # IndexError: no such sample in the log. FileNotFoundError: the
                # destination log doesn't exist yet (before log_start's flush).
                return None
        return sample

    def sample_events_provider(
        self, id: str | int, epoch: int
    ) -> "TranscriptHistoryProvider | None":
        """History provider over the realtime buffer for one sample, or None.

        The events counterpart to :meth:`sample_summaries` / :meth:`read_sample`,
        handed to the control channel via ``register_eval``: events for a
        streaming-completion sample (whose recorder copy is event-less — they
        live in the buffer database) are read through the *same* buffer
        instance this logger writes. That keeps the control layer ignorant of
        what a buffer is (no path re-derivation, no second connection set) and
        puts its reads under the buffer's sample read leases, which defer
        removal while a read is open. Returns ``None`` when realtime logging
        is off or the buffer has been torn down — callers then fall back to
        the recorder/on-disk sample.
        """
        if self._buffer_db is None:
            return None
        from inspect_ai.log._recorders.buffer.transcript_history_provider import (
            BufferTranscriptHistoryProvider,
        )

        return BufferTranscriptHistoryProvider(self._buffer_db, id, epoch)

    async def complete_sample(self, sample: EvalSample, *, flush: bool) -> None:
        await self.recorder.log_sample(self.eval, sample)
        await self._finalize_sample(sample, flush=flush)

    async def complete_sample_streaming(
        self, sample: EvalSample, history: "SampleHistory", *, flush: bool
    ) -> None:
        await self.recorder.log_sample_streaming(self.eval, sample, history)
        await self._finalize_sample(sample, flush=flush)

    async def _finalize_sample(self, sample: EvalSample, *, flush: bool) -> None:
        # the recorder already holds this attempt's result: a seeded record
        # under the same key is superseded
        self._seeded_pending.discard(_seeded_key(sample.id, sample.epoch))
        if self._buffer_db is not None:
            self._buffer_db.complete_sample(
                sample.summary(), sample_metadata=sample.metadata
            )

        # flush=False leaves the sample in the recorder's buffer for whichever
        # flush comes next (a later threshold flush or the finish) rather than
        # counting it toward the threshold or arming the stale-flush timer
        if flush:
            async with self._flush_pending_lock:
                was_empty = not self.flush_pending
                self.flush_pending.append((sample.id, sample.epoch))
                threshold_reached = len(self.flush_pending) >= self.flush_buffer

            if threshold_reached:
                await self._stop_stale_flush_timer()
                await self._flush_pending_samples()
            elif was_empty:
                await self._start_stale_flush_timer_if_needed()

        self._record_sample_outcome(sample)

    def _record_sample_outcome(self, sample: EvalSample) -> None:
        key = (sample.id, sample.epoch)
        self._logged_sample_keys.add(key)
        # a seeded record is resolved: accepted by the sweep as-is, or
        # superseded by its re-run's completion
        self._seeded_pending.discard(_seeded_key(sample.id, sample.epoch))
        # same classifier the read/requeue/retry surfaces use to tell a
        # cancelled sample from an errored one; discard on re-log so a
        # requeued cancelled sample's re-run counts again
        if sample.error is not None and is_cancellation_message(sample.error.message):
            self._cancelled_sample_keys.add(key)
        else:
            self._cancelled_sample_keys.discard(key)
        if sample.error is None:
            self._samples_completed += 1

    async def _flush_pending_samples(
        self, *, stale_flush_generation: int | None = None
    ) -> int:
        """Flush buffered completed samples to the log; return the count written.

        Shared by every flush path — the buffer-full flush and the stale-flush
        timer (which ignore the return) and the on-demand ``flush_samples()``.
        Serialized via :attr:`_flush_lock`; a no-op returning 0 once the eval
        has finished or been discarded (the recorder has been torn down,
        so reaching into it would raise) or when nothing is pending.
        """
        reschedule_stale_flush = False
        flushed = 0
        async with self._flush_lock:
            if self._finished or self._discarded:
                return 0
            async with self._flush_pending_lock:
                pending = list(self.flush_pending)
                if not pending:
                    return 0

            await self.recorder.flush(self.eval)
            flushed = len(pending)

            async with self._flush_pending_lock:
                if self._buffer_db is not None:
                    self._buffer_db.remove_samples(pending)

                # Items appended during the flush are at the tail; drop the flushed prefix.
                del self.flush_pending[: len(pending)]
                current_generation = self._stale_flush_generation
                reschedule_stale_flush = bool(self.flush_pending) and (
                    stale_flush_generation is None
                    or stale_flush_generation == current_generation
                )

        if reschedule_stale_flush:
            await self._arm_stale_flush_timer(generation=stale_flush_generation)
        return flushed

    async def flush_samples(self) -> int:
        """Write all buffered completed samples to the log immediately.

        Completed samples normally accumulate until ``log_buffer`` of them queue
        up (or the stale-flush timer fires) before a (possibly remote) write.
        This forces that write now — so the samples become readable in the log
        without waiting — and returns the number written (0 if none were
        pending or the eval has finished). Handed to the control channel via
        ``register_eval`` so ``inspect ctl task log-flush`` can push a
        long-running eval's results out to S3 on demand.
        """
        # an on-demand flush writes everything pending, so quiesce the stale
        # timer first (it would otherwise wake to find nothing left to do)
        await self._stop_stale_flush_timer()
        try:
            return await self._flush_pending_samples()
        except Exception:
            # the flush failed with samples still pending; re-arm the stale-flush
            # timer we stopped above so they're retried automatically rather than
            # stranded until the next sample completes (mirrors the stale path's
            # own on-failure re-arm). The error still propagates to the caller.
            await self._arm_stale_flush_timer()
            raise

    def buffer_config(
        self, log_buffer: int | None = None, log_shared: int | None = None
    ) -> "BufferConfig":
        """Get (and optionally update) this eval's sample-buffer parameters.

        With both arguments ``None`` this is a pure read. ``log_buffer`` sets
        the number of completed samples to buffer before a log write (clamped
        to a minimum of 1); ``log_shared`` *retunes* an already-running
        shared-log sync interval (in seconds).

        Updating ``log_buffer`` changes the threshold for *future* writes only —
        it does not flush samples already buffered under the previous threshold.
        Lowering it therefore takes effect when the next sample finalizes and
        crosses the new threshold; to write what's already pending now, use
        ``inspect ctl task log-flush``. (Keeping the directive policy-only avoids coupling
        a parameter change to a possibly-remote write.)

        ``log_shared`` cannot turn shared sync on at runtime: a buffer started
        without it has no filestore (a normal CLI run passes ``log_shared=0``),
        so the request is rejected and reported back as ``log_shared=None``
        ("off") rather than echoing a value that won't take effect. It's also a
        no-op when realtime logging — and thus the buffer database — is off.
        Returns the resulting configuration. Handed to the control channel via
        ``register_eval`` for ``inspect ctl config``.
        """
        from inspect_ai._control.eval_state import BufferConfig

        if log_buffer is not None:
            self.flush_buffer = max(1, log_buffer)
        if log_shared is not None and self._buffer_db is not None:
            # returns False (a no-op) when this buffer has no shared sync to
            # retune — the reported log_shared below stays None, so the rejected
            # request isn't echoed back as if it had been applied
            self._buffer_db.set_sync_interval(log_shared)
        return BufferConfig(
            log_buffer=self.flush_buffer,
            pending=len(self.flush_pending),
            log_shared=self._buffer_db.shared_sync_interval
            if self._buffer_db is not None
            else None,
        )

    async def record_inherited_config_updates(self) -> None:
        """Record process-scoped ctl retunes this log hasn't yet captured.

        A watermark (``_process_updates_recorded``) tracks how far into the
        run's accumulated process-scoped updates this log has recorded.
        Called at the two points that bracket the gap between "logger
        exists" and "logger is a live fan-out target": from :meth:`init`, to
        snapshot retunes that predate the log (a retry attempt or a later
        eval-set child); and from ``task_run`` immediately before
        ``register_eval``, because all of a run's initial loggers are
        init()ed up front in ``prepare_options`` while retunes fan out only
        to *registered* evals — without the catch-up, a task queued behind
        ``--max-tasks`` would never record a retune applied while it waited,
        even though the process-global override still governs it. The
        catch-up must precede ``register_eval``: both run on the eval's
        single event loop and ``register_eval`` is sync, so no retune can
        land between the final watermark check here and registration (after
        which fan-out reaches this logger directly).

        Recorded copies keep their original provenance/timestamps and are
        marked ``inherited`` via ``provenance.metadata``. Recording is
        bookkeeping, never control: a failure degrades to a warning (and
        advances the watermark — no retry) rather than blocking the task.
        """
        from inspect_ai._control.config_record import (
            inherited_config_updates,
            process_config_update_count,
        )

        # re-check the count after each batch: recording awaits the recorder,
        # and a retune can land during those awaits
        while self._process_updates_recorded < process_config_update_count():
            updates = inherited_config_updates(self._process_updates_recorded)
            self._process_updates_recorded += len(updates)
            for update in updates:
                try:
                    await self.log_config_update(update)
                except Exception as ex:
                    logger.warning(
                        "Could not record inherited config update in eval log %s: %s",
                        self._location,
                        ex,
                    )

    async def log_config_update(self, update: "ConfigUpdate") -> bool:
        """Record a mid-run config change into this eval's log.

        Handed to the control channel via ``register_eval`` so applied
        ``inspect ctl config`` retunes are persisted (see
        ``EvalLog.config_updates``). Missing ``previous`` values are filled
        from this log's launch config before recording, so each affected log
        reports its own honest "before". Returns ``False`` (recording
        nothing) once finish or discard has torn the recorder down — a finished
        log's record is complete, and under ``--ctl-server=keep`` the logger
        stays attached to the eval's state after finishing.

        Serialized under ``_flush_lock`` with the other recorder-touching
        paths so it can't interleave with a flush or the finish teardown.
        """
        from inspect_ai.log._config_update import fill_previous_from_launch

        async with self._flush_lock:
            if self._finished or self._discarded:
                return False
            update = fill_previous_from_launch(update, self.eval)
            await self.recorder.log_config_update(self.eval, update)
            return True

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        if self._buffer_db is not None:
            self._buffer_db.update_metrics(metrics)

    async def _start_stale_flush_timer_if_needed(self) -> None:
        await self._arm_stale_flush_timer()

    async def _arm_stale_flush_timer(self, *, generation: int | None = None) -> None:
        async with self._flush_pending_lock:
            # never arm once log_finish() has begun finalizing — it has (or is
            # about to) clear pending and tear down, so a timer here is stale
            if self._finished or self._discarded:
                return
            if generation is not None and generation != self._stale_flush_generation:
                return

            should_start = 0 < len(self.flush_pending) < self.flush_buffer
            already_started = self._stale_flush_cancel_scope is not None
            if not should_start or already_started:
                return

            cancel_scope = anyio.CancelScope()
            stopped = anyio.Event()
            current_generation = self._stale_flush_generation
            self._stale_flush_cancel_scope = cancel_scope
            self._stale_flush_stops.add(stopped)

        try:
            run_in_background(
                self._stale_flush_after_delay,
                cancel_scope,
                stopped,
                current_generation,
            )
        except Exception:
            # The background task never started, so its finally won't run; this
            # is the only path that signals `stopped`. Shield so a cancellation
            # here can't skip stopped.set() and strand a _stop_stale_flush_timer()
            # waiter (mirrors the shielded teardown in _stale_flush_after_delay).
            with anyio.CancelScope(shield=True):
                async with self._flush_pending_lock:
                    if self._stale_flush_cancel_scope is cancel_scope:
                        self._stale_flush_cancel_scope = None
                    self._stale_flush_stops.discard(stopped)
                stopped.set()
            raise

    async def _stop_stale_flush_timer(self) -> None:
        async with self._flush_pending_lock:
            self._stale_flush_generation += 1
            if self._stale_flush_cancel_scope is not None:
                self._stale_flush_cancel_scope.cancel()
                self._stale_flush_cancel_scope = None
            stopped_events = list(self._stale_flush_stops)

        for stopped in stopped_events:
            await stopped.wait()

    async def cleanup(self, *, keep_buffer: bool = False) -> None:
        await self._stop_stale_flush_timer()
        await self._release_buffer_db(keep=keep_buffer)

    async def _release_buffer_db(self, *, keep: bool) -> None:
        """Close (``keep``, preserving recovery files) or delete the realtime buffer."""
        buffer_db = self._buffer_db
        if buffer_db is None:
            return
        # a cancellation landing before the teardown's worker thread starts
        # must not orphan the buffer (its SQLite connections and sync thread
        # would stay open with nothing left to close them): hand over the
        # reference and tear down under one shield
        with anyio.CancelScope(shield=True):
            self._buffer_db = None
            if keep:
                await buffer_db.aclose()
            else:
                await buffer_db.acleanup()

    async def discard(
        self, *, keep_destination: bool = False, keep_buffer: bool = False
    ) -> None:
        """Discard this attempt's never-finished log.

        Beyond :meth:`cleanup` (stale-flush timer + realtime buffer db),
        drops the recorder's in-memory entry for this eval — ``log_finish``
        never runs for it, so the entry would otherwise live for the rest of
        the run — and, unless ``keep_destination`` is set, removes a
        destination file the attempt already flushed. For an abandoned retry
        (``log_start`` flushed the seeded prior set and nothing ran) that
        file is a stray: a ``started`` log that would otherwise win the
        end-of-run retry-cleanup sweep by mtime, deleting the errored
        attempt's log that must stand as the task's final state. For an
        attempt whose startup or final write failed the file is kept:
        it holds every sample flushed so far, which the next attempt seeds
        from — sample progress outranks the header it lacks.

        ``keep_buffer`` closes the realtime buffer without deleting its SQLite
        or shared files. Terminal failures preserve these for recovery: they
        may contain completed samples that never reached the destination.

        Failures are contained (logged as a warning) rather than raised:
        callers run inside the dispatcher task group, where an escaping
        storage error (e.g. a transient remote-fs failure on the file
        removal) would cancel every in-flight task in the run. Worst case a
        failed removal leaves the same stray ``started`` log the crash
        would have left anyway. Each step is contained on its own so a
        failed buffer-db removal in ``cleanup`` doesn't skip the recorder
        drop — the entry leak is the very thing this method exists to close.
        Detaches control handlers and quiesces already captured flush/config
        calls before dropping their recorder. A discarded log is not marked
        finished: its destination may never have been written.
        """
        from inspect_ai._control.eval_state import detach_eval_live

        detach_eval_live(self.eval.eval_id)
        async with self._flush_lock:
            self._discarded = True
            async with self._flush_pending_lock:
                self.flush_pending = []
        try:
            await self.cleanup(keep_buffer=keep_buffer)
        except Exception as ex:
            logger.warning(
                f"Error cleaning up abandoned log entry '{self.location}': {ex}"
            )
        try:
            await self.recorder.log_discard(
                self.eval, keep_destination=keep_destination
            )
        except Exception as ex:
            logger.warning(
                f"Error discarding abandoned log entry '{self.location}': {ex}"
            )

    async def _clear_stale_flush_timer(
        self, cancel_scope: anyio.CancelScope, stopped: anyio.Event
    ) -> None:
        async with self._flush_pending_lock:
            if self._stale_flush_cancel_scope is cancel_scope:
                self._stale_flush_cancel_scope = None

    async def _stale_flush_after_delay(
        self,
        cancel_scope: anyio.CancelScope,
        stopped: anyio.Event,
        generation: int,
    ) -> None:
        try:
            with cancel_scope:
                await anyio.sleep(self._stale_flush_interval)
                await self._clear_stale_flush_timer(cancel_scope, stopped)
                try:
                    with anyio.CancelScope(shield=True):
                        await self._flush_pending_samples(
                            stale_flush_generation=generation
                        )
                except Exception as ex:
                    logger.warning("Stale eval log flush failed: %s", ex, exc_info=ex)
                    await self._arm_stale_flush_timer(generation=generation)
        finally:
            # Teardown may run with the enclosing scope already cancelled. The
            # lock acquire is a cancellation checkpoint, so without shielding it
            # can raise and skip stopped.set() — leaving the (shielded) wait in
            # _stop_stale_flush_timer() hung forever.
            with anyio.CancelScope(shield=True):
                async with self._flush_pending_lock:
                    self._stale_flush_stops.discard(stopped)
                stopped.set()

    async def log_finish(
        self,
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None = None,
        reductions: list[EvalSampleReductions] | None = None,
        error: EvalError | None = None,
        prune_unplanned: bool = False,
    ) -> EvalLog:
        """Finish this attempt's log.

        ``prune_unplanned`` (a natural success only — the attempt realized
        its whole plan, nothing was abandoned) drops the seeded prior records
        no sample of this attempt resolved (still in ``_seeded_pending``).
        A static plan pruned its unplanned keys at the seed and consulted
        every planned one, so the set is empty; for a dynamic feed, seeded
        with every prior record, it is exactly the keys the feed did not
        produce this time — records of samples outside this attempt's plan,
        which would otherwise stand in a success log beside a
        ``total_samples`` and metrics that exclude them. A graceful
        resolution (score/error/drain) abandoned queued samples whose seeded
        records the next pass reuses, so it never prunes.
        """
        # quiesce the stale-flush timer first — _stop_stale_flush_timer waits
        # for any in-flight timer flush to complete, so it can't race the teardown
        await self._stop_stale_flush_timer()

        # Finalize under `_flush_lock` so an on-demand `flush_samples()` from the
        # control channel can't interleave with the teardown: `recorder.log_finish`
        # deletes this eval's tracked log, and a flush racing that would call
        # `recorder.flush()` on the gone log (KeyError -> 500). The lock makes
        # finish and flush mutually exclusive; the `_finished` flag set inside it
        # makes any flush that acquires the lock afterward a no-op rather than
        # touching the torn-down recorder.
        async with self._flush_lock:
            if prune_unplanned and status == "success" and self._seeded_pending:
                await self.recorder.log_prune(self.eval, set(self._seeded_pending))

            # finish and get log
            log = await self.recorder.log_finish(
                self.eval, status, stats, results, reductions, error, self.header_only
            )

            # every completed sample is now on disk. Mark finished and drop the
            # pending list so the still-attached flush/buffer directives (kept
            # visible under --ctl-server=keep) report a finished no-op / accurate
            # empty pending rather than reporting stale pending.
            self._finished = True
            self._seeded_pending.clear()
            async with self._flush_pending_lock:
                self.flush_pending.clear()

            # cleanup the events db
            await self._release_buffer_db(keep=False)

        # An on-demand flush_samples() that was mid-flush while we waited on
        # _flush_lock above re-arms the stale-flush timer *outside* _flush_lock
        # (see _flush_pending_samples), so it can slip in after our pre-lock stop
        # and leave a timer armed against the now-finished eval. Now that
        # _finished is set and pending cleared, stop once more to cancel it — and
        # not while holding _flush_lock, since the stop awaits any in-flight
        # timer flush, which takes that lock.
        await self._stop_stale_flush_timer()

        # return log
        return log


def plan_to_eval_plan(plan: Plan, config: GenerateConfig) -> EvalPlan:
    def eval_plan_step(solver: Solver) -> EvalPlanStep:
        return EvalPlanStep(
            solver=registry_log_name(solver),
            params=getattr(solver, SOLVER_ALL_PARAMS_ATTR, {}),
            params_passed=registry_params(solver),
        )

    eval_plan = EvalPlan(
        name=plan.name,
        steps=[eval_plan_step(solver) for solver in plan.steps],
        finish=eval_plan_step(plan.finish) if plan.finish else None,
        config=config,
    )
    if plan.finish:
        eval_plan.steps.append(eval_plan_step(plan.finish))
    return eval_plan


def collect_eval_data(stats: EvalStats) -> None:
    from inspect_ai.log._log import ConnectionLimitChange
    from inspect_ai.util._concurrency import adaptive_controllers

    # collect stats
    stats.completed_at = iso_now()
    stats.model_usage = model_usage()
    stats.role_usage = role_usage()

    # capture adaptive-connections controller history. The tuple's second
    # element is the controller's display name (model name), NOT the underlying
    # connection_key (which often contains an api_key) — see _set_limit.
    history: list[ConnectionLimitChange] = []
    for controller in adaptive_controllers():
        for ts, model, old, new, reason in controller.history:
            history.append(
                ConnectionLimitChange(
                    timestamp=ts,
                    model=model,
                    old_limit=old,
                    new_limit=new,
                    reason=reason,
                )
            )
    history.sort(key=lambda e: e.timestamp)
    stats.connection_limit_history = history


def resolve_eval_metrics(
    metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
    | dict[str, list[MetricSpec]]
    | None,
) -> (
    list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
    | dict[str, list[EvalMetricDefinition]]
    | None
):
    if metrics is None:
        return None
    elif isinstance(metrics, list):
        result: list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]] = []
        for metric_item in metrics:
            if isinstance(metric_item, dict):
                # It's a dict of metric groups
                result.append(
                    {
                        k: [
                            EvalMetricDefinition(name=v.metric, options=v.args)
                            for v in metric_list
                        ]
                        for k, metric_list in metric_item.items()
                    }
                )
            else:
                # It's a direct MetricSpec
                result.append(
                    EvalMetricDefinition(
                        name=metric_item.metric, options=metric_item.args
                    )
                )
        return result
    else:
        return {
            k: [
                EvalMetricDefinition(name=v.metric, options=v.args) for v in metric_list
            ]
            for k, metric_list in metrics.items()
        }


def resolve_eval_scorers(scorers: list[ScorerSpec] | None) -> list[EvalScorer] | None:
    if scorers is None:
        return None
    else:
        results = []
        for scorer in scorers:
            results.append(
                EvalScorer(
                    name=scorer.scorer,
                    metrics=resolve_scorer_metrics(scorer.metrics),
                    options=scorer.args,
                    metadata=scorer.metadata,
                )
            )
        return results


def resolve_scorer_metrics(
    metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
    | dict[str, list[MetricSpec]]
    | None,
) -> (
    list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
    | dict[str, list[EvalMetricDefinition]]
    | None
):
    if metrics is None:
        return None
    elif isinstance(metrics, list):
        resolved_metrics: list[
            EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]
        ] = []
        for metric_item in metrics:
            if isinstance(metric_item, MetricSpec):
                resolved_metrics.append(
                    EvalMetricDefinition(
                        name=metric_item.metric, options=metric_item.args
                    )
                )
            elif isinstance(metric_item, dict):
                resolved_metrics.append(
                    {
                        metric_group: [
                            EvalMetricDefinition(
                                name=metric_spec.metric, options=metric_spec.args
                            )
                            for metric_spec in metric_specs
                        ]
                        for metric_group, metric_specs in metric_item.items()
                    }
                )
            else:
                raise TypeError(f"Unexpected item in list: {metric_item}")
        return resolved_metrics
    else:
        return {
            metric_group: [
                EvalMetricDefinition(name=metric_spec.metric, options=metric_spec.args)
                for metric_spec in metric_specs
            ]
            for metric_group, metric_specs in metrics.items()
        }
