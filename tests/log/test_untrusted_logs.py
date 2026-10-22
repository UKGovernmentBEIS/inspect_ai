"""Read operations on a log someone else wrote must not run code the log names.

Recomputing metrics, editing a score, recovering a crashed log and eval-set
recovery may not import a file because a log names it, nor construct a model
or a non-metric registry object from the log's metric options, unless the
caller passes `trust_log=True`. Rescoring with the caller's own scorers
treats the log's metrics the same way.

Each fixture isolates one protection. A marker module records each import of
it in a file, and a spy on `get_model` records models built with the
fixtures' distinctive base URL (which appears only in metric options).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZipFile

import pytest
from click.testing import CliRunner
from pydantic_core import to_jsonable_python
from test_helpers.buffer import simulate_crashed_buffer_db

import inspect_ai.model._model as model_module
from inspect_ai import eval, eval_retry, score
from inspect_ai._cli.log import recover_command
from inspect_ai._eval.evalset import _recover_crashed_log
from inspect_ai._eval.score import SCORE_OPT_IN, TRUST_LOG_OPT_IN, score_async
from inspect_ai._eval.task.results import ScorerInfo
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.file import local_path
from inspect_ai._util.registry import (
    DisallowedRegistryArg,
    _registry,
    registry_key,
    registry_unqualified_name,
)
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.log import EvalLogInfo, EvalSampleSummary, write_eval_log_async
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalMetricDefinition,
    EvalPlan,
    EvalSample,
    EvalScorer,
    EvalSpec,
)
from inspect_ai.log._metric import recompute_metrics
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import LogStart
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover import (
    read_buffer_recovery_data,
    recover_eval_log,
)
from inspect_ai.log._score import edit_score
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    accuracy,
    match,
    metric,
    scorer,
)
from inspect_ai.scorer._metric import ScoreEdit
from inspect_ai.solver import TaskState

SCORER_METRIC = "untrusted_scorer_metric"
TASK_METRIC = "untrusted_task_metric"
UNTRUSTED_URL = "https://untrusted.invalid/v1"
MODEL_DICT = {
    "model": "mockllm/model",
    "config": {},
    "base_url": UNTRUSTED_URL,
    "model_args": {},
}
SOLVER_DICT = {"type": "solver", "name": "generate", "params": {}}

options_metric_calls: list[Any] = []


@metric
def untrusted_options_metric(option: Any = None) -> Metric:
    options_metric_calls.append(option)

    def compute(scores: list[SampleScore]) -> float:
        return 1.0

    return compute


@metric
def registry_shaped_args_metric(type: str, name: str, params: dict[str, Any]) -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 1.0

    return compute


scored_samples: list[Any] = []


@scorer(metrics=[accuracy()])
def counting_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        scored_samples.append(state.sample_id)
        return Score(value="C")

    return score


# --- fixtures ------------------------------------------------------------------


@pytest.fixture
def imports(tmp_path: Path) -> Path:
    """File the marker modules append to when imported."""
    return tmp_path / "imports.txt"


def _imported(imports: Path) -> list[str]:
    return imports.read_text().splitlines() if imports.exists() else []


def _marker_source(imports: Path) -> str:
    return f"with open({str(imports)!r}, 'a') as f:\n    f.write(__file__ + '\\n')\n"


@pytest.fixture
def marker(tmp_path: Path, imports: Path) -> Path:
    """A module that defines nothing but records its import."""
    path = tmp_path / "marker.py"
    path.write_text(_marker_source(imports))
    return path


@pytest.fixture
def task_file(tmp_path: Path, imports: Path) -> Path:
    """A task file that defines a scorer metric and a task-level metric."""
    path = tmp_path / "untrusted_task.py"
    path.write_text(
        _marker_source(imports)
        + f"""
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset
from inspect_ai.scorer import Metric, SampleScore, metric


@metric
def {SCORER_METRIC}() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 0.25

    return compute


@metric
def {TASK_METRIC}() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 0.5

    return compute


@task
def untrusted_task():
    return Task(dataset=MemoryDataset([]))
"""
    )
    return path


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    def clear() -> None:
        for name in (SCORER_METRIC, TASK_METRIC):
            _registry.pop(registry_key("metric", name), None)
        options_metric_calls.clear()
        scored_samples.clear()

    clear()
    yield
    clear()


@pytest.fixture
def untrusted_models(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on get_model: the base URLs of models built from UNTRUSTED_URL."""
    built: list[str] = []
    real_get_model = model_module.get_model

    def spy(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("base_url") == UNTRUSTED_URL:
            built.append(UNTRUSTED_URL)
        return real_get_model(*args, **kwargs)

    monkeypatch.setattr(model_module, "get_model", spy)
    monkeypatch.setattr("inspect_ai._eval.score.get_model", spy)
    return built


FORBIDDEN_OPTIONS: dict[str, tuple[EvalMetricDefinition, str]] = {
    "model": (
        EvalMetricDefinition(
            name="untrusted_options_metric", options={"option": MODEL_DICT}
        ),
        "Metric 'untrusted_options_metric' option 'option': a model",
    ),
    "nested_model": (
        EvalMetricDefinition(
            name="untrusted_options_metric",
            options={"option": {"inner": [MODEL_DICT]}},
        ),
        "Metric 'untrusted_options_metric' option 'option.inner.0': a model",
    ),
    "solver": (
        EvalMetricDefinition(
            name="untrusted_options_metric", options={"option": SOLVER_DICT}
        ),
        "option 'option': a solver ('generate')",
    ),
    "grouped": (
        EvalMetricDefinition(
            name="grouped",
            options={
                "metric": {
                    "type": "metric",
                    "name": "untrusted_options_metric",
                    "params": {"option": MODEL_DICT},
                },
                "group_key": "category",
            },
        ),
        "Metric 'grouped' option 'metric.params.option': a model",
    ),
}


def _log(
    *,
    task_file: Path | None = None,
    scorer_metrics: list[EvalMetricDefinition] | None = None,
    eval_metrics: list[EvalMetricDefinition] | None = None,
    keys: tuple[str, ...] = ("match", "extra"),
    epochs_reducer: list[str] | None = None,
) -> EvalLog:
    """A log with two scored samples.

    "match" is the recorded scorer (its metrics are `scorer_metrics`);
    "extra" is a score key no scorer produced, which gets the task-level
    metrics (`eval_metrics`) or the defaults.
    """
    return EvalLog(
        status="success",
        eval=EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="untrusted_task",
            task_file=task_file.as_posix() if task_file else None,
            dataset=EvalDataset(samples=2, sample_ids=[1, 2]),
            model="mockllm/model",
            config=EvalConfig(epochs_reducer=epochs_reducer),
            metrics=list(eval_metrics) if eval_metrics else None,
            scorers=[
                EvalScorer(
                    name="match",
                    metrics=list(
                        scorer_metrics or [EvalMetricDefinition(name="accuracy")]
                    ),
                )
            ],
        ),
        samples=[
            EvalSample(
                id=id,
                epoch=1,
                input="input",
                target="C",
                scores={key: Score(value="C") for key in keys},
            )
            for id in (1, 2)
        ],
    )


def _fixture(name: str, task_file: Path) -> EvalLog:
    """Fixtures 2s/2t/2b (task-file metrics) and 3s/3t (forbidden options)."""
    scorer_metric = EvalMetricDefinition(name=SCORER_METRIC)
    task_metric = EvalMetricDefinition(name=TASK_METRIC)
    forbidden = FORBIDDEN_OPTIONS["model"][0]
    match name:
        case "2s":
            return _log(task_file=task_file, scorer_metrics=[scorer_metric])
        case "2t":
            return _log(task_file=task_file, eval_metrics=[task_metric])
        case "2b":
            return _log(
                task_file=task_file,
                scorer_metrics=[scorer_metric],
                eval_metrics=[task_metric],
            )
        case "3s":
            return _log(scorer_metrics=[forbidden])
        case "3t":
            return _log(eval_metrics=[forbidden])
    raise ValueError(name)


def _expected_error(name: str) -> tuple[type[Exception], str]:
    if name == "2s":
        return LookupError, f"Metric '{SCORER_METRIC}' (used by scorer 'match')"
    elif name == "2t":
        return LookupError, f"Metric '{TASK_METRIC}' (a task-level metric)"
    else:
        return DisallowedRegistryArg, FORBIDDEN_OPTIONS["model"][1]


# --- score keys ----------------------------------------------------------------


def test_score_keys_naming_files_are_not_imported(marker: Path, imports: Path) -> None:
    log = _log(keys=(f"{marker.as_posix()}@hostile", marker.as_posix()))
    log.eval.scorers = None

    recompute_metrics(log)

    assert _imported(imports) == []
    assert log.results is not None
    for eval_score in log.results.scores:
        assert set(eval_score.metrics) == {"accuracy", "stderr"}


def test_score_key_of_scorer_needing_arguments_gets_default_metrics() -> None:
    info = ScorerInfo.from_name("pattern")
    assert isinstance(info.metrics, list)
    assert [registry_unqualified_name(m) for m in info.metrics] == [
        "accuracy",
        "stderr",
    ]


# --- recompute -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["2s", "2t"])
def test_recompute_does_not_import_task_file_for_metrics(
    name: str, task_file: Path, imports: Path
) -> None:
    error, message = _expected_error(name)
    with pytest.raises(error) as ex:
        recompute_metrics(_fixture(name, task_file))
    assert message in str(ex.value)
    assert f"task file ('{task_file.as_posix()}')" in str(ex.value)
    assert str(ex.value).endswith(TRUST_LOG_OPT_IN)
    assert _imported(imports) == []


def test_recompute_missing_extension_metric_raises_lookup_error() -> None:
    log = _log(scorer_metrics=[EvalMetricDefinition(name="somepkg/nope")])
    with pytest.raises(LookupError, match="Metric 'somepkg/nope'.*trust_log=True"):
        recompute_metrics(log)


@pytest.mark.parametrize("variant", FORBIDDEN_OPTIONS)
@pytest.mark.parametrize("source", ["scorer", "task"])
def test_recompute_refuses_forbidden_metric_options(
    variant: str, source: str, untrusted_models: list[str]
) -> None:
    definition, message = FORBIDDEN_OPTIONS[variant]
    log = (
        _log(scorer_metrics=[definition])
        if source == "scorer"
        else _log(eval_metrics=[definition])
    )

    with pytest.raises(DisallowedRegistryArg) as ex:
        recompute_metrics(log)

    assert message in str(ex.value)
    assert str(ex.value).endswith(TRUST_LOG_OPT_IN)
    assert untrusted_models == []
    # refused before the metric factory ran
    assert options_metric_calls == []


REGISTRY_SHAPED = {"type": "metric", "name": "not_a_metric", "params": {}}


@pytest.mark.parametrize(
    "definition",
    [
        # the argument mapping itself looks like a registry dict
        EvalMetricDefinition(
            name="registry_shaped_args_metric", options=REGISTRY_SHAPED
        ),
        # so does the params mapping of a nested metric
        EvalMetricDefinition(
            name="untrusted_options_metric",
            options={
                "option": {
                    "type": "metric",
                    "name": "registry_shaped_args_metric",
                    "params": REGISTRY_SHAPED,
                }
            },
        ),
    ],
    ids=["top_level", "nested_params"],
)
@pytest.mark.parametrize("source", ["scorer", "task"])
@pytest.mark.parametrize("trust_log", [False, True])
def test_recompute_treats_argument_mappings_as_arguments(
    definition: EvalMetricDefinition, source: str, trust_log: bool
) -> None:
    log = (
        _log(scorer_metrics=[definition])
        if source == "scorer"
        else _log(eval_metrics=[definition])
    )

    recompute_metrics(log, trust_log=trust_log)

    assert log.results is not None


@pytest.mark.parametrize("container", ["config", "model_args"])
@pytest.mark.parametrize("source", ["scorer", "task"])
def test_recompute_does_not_look_for_metrics_inside_model_dicts(
    container: str, source: str, untrusted_models: list[str]
) -> None:
    model = {**MODEL_DICT, container: {"extra_body": REGISTRY_SHAPED}}
    definition = EvalMetricDefinition(
        name="untrusted_options_metric", options={"option": model}
    )

    def make() -> EvalLog:
        return (
            _log(scorer_metrics=[definition])
            if source == "scorer"
            else _log(eval_metrics=[definition])
        )

    # untrusted, the model is still refused where it would be built
    with pytest.raises(DisallowedRegistryArg):
        recompute_metrics(make())
    assert untrusted_models == []

    log = make()
    recompute_metrics(log, trust_log=True)

    assert log.results is not None
    assert untrusted_models == [UNTRUSTED_URL]


def test_recompute_untrusted_allows_nested_metrics() -> None:
    grouped = EvalMetricDefinition(
        name="grouped",
        options={
            "metric": {"type": "metric", "name": "accuracy", "params": {}},
            "group_key": "category",
        },
    )
    log = _log(scorer_metrics=[grouped])
    for sample in log.samples or []:
        sample.metadata = {"category": "a"}

    recompute_metrics(log)

    assert log.results is not None
    assert "all" in log.results.scores[0].metrics


def test_recompute_trusted_imports_task_file_once(
    task_file: Path, imports: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = _fixture("2b", task_file)

    with caplog.at_level(logging.INFO, logger="inspect_ai"):
        recompute_metrics(log, trust_log=True)

    assert _imported(imports) == [str(task_file)]
    records = [r for r in caplog.records if "Imported task file" in r.message]
    assert len(records) == 1
    assert str(task_file.absolute()) in records[0].message
    assert log.results is not None
    metrics = {s.name: s.metrics for s in log.results.scores}
    assert metrics["match"][SCORER_METRIC].value == 0.25
    assert metrics["extra"][TASK_METRIC].value == 0.5


def test_recompute_trusted_rebuilds_model_options(
    untrusted_models: list[str],
) -> None:
    log = _log(scorer_metrics=[FORBIDDEN_OPTIONS["model"][0]])

    recompute_metrics(log, trust_log=True)

    assert untrusted_models == [UNTRUSTED_URL]
    assert log.results is not None
    assert log.results.scores[0].metrics["untrusted_options_metric"].value == 1.0


def test_recompute_missing_reducer_names_it() -> None:
    log = _log(epochs_reducer=["no_such_reducer"])
    with pytest.raises(LookupError) as ex:
        recompute_metrics(log)
    assert "Epoch reducer 'no_such_reducer'" in str(ex.value)
    assert "trust_log" not in str(ex.value)


# --- edit_score ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["2s", "2t", "3s", "3t"])
def test_failed_edit_leaves_log_unchanged(
    name: str, task_file: Path, imports: Path, untrusted_models: list[str]
) -> None:
    log = _fixture(name, task_file)
    before = log.model_dump()
    edit = ScoreEdit(value="I")

    with pytest.raises(_expected_error(name)[0]):
        edit_score(log, 1, "match", edit)

    assert log.model_dump() == before
    assert _imported(imports) == [] and untrusted_models == []

    edit_score(log, 1, "match", edit, trust_log=True)

    sample = (log.samples or [])[0]
    assert sample.scores is not None
    assert sample.scores["match"].value == "I"
    # the original value and the edit, once
    assert len(sample.scores["match"].history) == 2
    assert sum(isinstance(e, ScoreEditEvent) for e in sample.events) == 1
    assert log.results is not None


# --- recovery ------------------------------------------------------------------


def _model_event() -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content="C"),
    )


def _crash(
    log: EvalLog, path: Path, keys: tuple[str, ...] = ("match", "extra")
) -> SampleBufferDatabase:
    """Write `log` as a crashed .eval with a buffer: sample 1 done, 2 running."""
    start = LogStart(version=LOG_SCHEMA_VERSION, eval=log.eval, plan=EvalPlan())
    with ZipFile(path, "w") as zf:
        zf.writestr(
            "_journal/start.json",
            json.dumps(to_jsonable_python(start, exclude_none=True)),
        )

    buffer = SampleBufferDatabase(path.as_posix(), create=True)
    now = datetime.now(timezone.utc).isoformat()
    for id, done in ((1, True), (2, False)):
        summary = EvalSampleSummary(
            id=id, epoch=1, input="input", target="C", started_at=now
        )
        buffer.start_sample(summary)
        buffer.log_events([SampleEvent(id=id, epoch=1, event=_model_event())])
        if done:
            summary.scores = {key: Score(value="C") for key in keys}
            summary.completed_at = now
            buffer.complete_sample(summary, sample_metadata=None)
    simulate_crashed_buffer_db(buffer)
    return buffer


@pytest.fixture
def crashed(tmp_path: Path) -> Iterator[Any]:
    buffers: list[SampleBufferDatabase] = []

    def make(log: EvalLog, keys: tuple[str, ...] = ("match", "extra")) -> Path:
        path = tmp_path / "logs" / "crashed.eval"
        path.parent.mkdir(exist_ok=True)
        buffers.append(_crash(log, path, keys))
        return path

    yield make
    for buffer in buffers:
        buffer.cleanup()


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("name", ["2s", "2t", "3s", "3t"])
def test_failed_recovery_writes_nothing(
    name: str,
    overwrite: bool,
    crashed: Any,
    task_file: Path,
    imports: Path,
    untrusted_models: list[str],
) -> None:
    path = crashed(_fixture(name, task_file))
    original = path.read_bytes()
    error, message = _expected_error(name)

    with pytest.raises(error) as ex:
        recover_eval_log(path.as_posix(), overwrite=overwrite)

    assert message in str(ex.value)
    assert str(ex.value).endswith(TRUST_LOG_OPT_IN)
    assert sorted(p.name for p in path.parent.iterdir()) == ["crashed.eval"]
    assert path.read_bytes() == original
    assert read_buffer_recovery_data(path.as_posix()) is not None
    assert _imported(imports) == [] and untrusted_models == []

    recovered = recover_eval_log(
        path.as_posix(), overwrite=overwrite, incomplete_action="error", trust_log=True
    )

    assert recovered.results is not None
    assert recovered.status == "success"


def test_failed_recovery_reducer_advice(crashed: Any) -> None:
    path = crashed(_log(epochs_reducer=["no_such_reducer"]))

    with pytest.raises(LookupError) as ex:
        recover_eval_log(path.as_posix())

    assert "Epoch reducer 'no_such_reducer'" in str(ex.value)
    assert "Nothing was written" in str(ex.value)
    assert "--trust-log" in str(ex.value)
    assert sorted(p.name for p in path.parent.iterdir()) == ["crashed.eval"]


def test_recover_cli_trust_log(crashed: Any, task_file: Path, imports: Path) -> None:
    path = crashed(_fixture("2s", task_file))
    runner = CliRunner()

    refused = runner.invoke(recover_command, [path.as_posix()])
    assert refused.exit_code == 1
    assert "--trust-log" in refused.output
    assert _imported(imports) == []

    trusted = runner.invoke(recover_command, [path.as_posix(), "--trust-log"])
    assert trusted.exit_code == 0, trusted.output
    assert "Recovered 2 samples" in trusted.output
    assert _imported(imports) == [str(task_file)]


# --- eval-set and eval-retry ------------------------------------------------------


def _log_info(path: Path, log: EvalLog) -> EvalLogInfo:
    return EvalLogInfo(
        name=path.as_posix(),
        type="file",
        size=path.stat().st_size,
        mtime=path.stat().st_mtime,
        task=log.eval.task,
        task_id=log.eval.task_id,
        suffix=None,
    )


@pytest.mark.parametrize(
    "case,message",
    [
        ("options_scorer", FORBIDDEN_OPTIONS["model"][1]),
        ("options_task", FORBIDDEN_OPTIONS["model"][1]),
        ("missing_metric", "Metric 'somepkg/nope' (used by scorer 'match')"),
        ("missing_reducer", "Epoch reducer 'no_such_reducer'"),
    ],
)
def test_eval_set_recovery_warns_and_recovers_without_results(
    case: str,
    message: str,
    crashed: Any,
    untrusted_models: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    match case:
        case "options_scorer":
            log = _fixture("3s", Path("unused"))
        case "options_task":
            log = _fixture("3t", Path("unused"))
        case "missing_metric":
            log = _log(scorer_metrics=[EvalMetricDefinition(name="somepkg/nope")])
        case _:
            log = _log(epochs_reducer=["no_such_reducer"])
    path = crashed(log)
    header = EvalLog(eval=log.eval, status="started", location=path.as_posix())

    with caplog.at_level(logging.WARNING, logger="inspect_ai"):
        recovered, info = _recover_crashed_log(header, _log_info(path, log))

    assert recovered.location is not None and "-recovered" in recovered.location
    assert Path(recovered.location).exists()
    assert info.name == recovered.location
    assert recovered.results is None
    warnings = [
        r.message for r in caplog.records if "Unable to recompute metrics" in r.message
    ]
    assert len(warnings) == 1
    assert message in warnings[0]
    # eval-set recovers anyway and has no trust_log option, so no rerun advice
    assert "Nothing was written" not in warnings[0]
    assert "trust_log" not in warnings[0]
    assert untrusted_models == []


def test_eval_set_recovery_gives_hostile_score_keys_default_metrics(
    crashed: Any, marker: Path, imports: Path
) -> None:
    log = _log()
    log.eval.scorers = None
    path = crashed(log, keys=(f"{marker.as_posix()}@hostile", marker.as_posix()))
    header = EvalLog(eval=log.eval, status="started", location=path.as_posix())

    recovered, _ = _recover_crashed_log(header, _log_info(path, log))

    assert recovered.results is not None
    for eval_score in recovered.results.scores:
        assert set(eval_score.metrics) == {"accuracy", "stderr"}
    assert _imported(imports) == []


def test_eval_retry_recovery_trusts_the_log(
    tmp_path: Path, imports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """eval-retry imports the task file anyway, so its recovery is trusted."""
    task_path = tmp_path / "retry_task.py"
    task_path.write_text(
        _marker_source(imports)
        + f"""
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, match, metric


@metric
def {TASK_METRIC}() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 0.5

    return compute


@task
def retry_task():
    return Task(
        dataset=[Sample(id=1, input="C", target="C"), Sample(id=2, input="C", target="C")],
        scorer=match(),
        metrics=[{TASK_METRIC}()],
    )
"""
    )
    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "logs"
    started = eval(
        task_path.name,
        model="mockllm/model",
        log_dir=log_dir.as_posix(),
        run_samples=False,
    )[0]
    assert started.location is not None
    assert started.eval.metrics is not None
    location = Path(local_path(started.location))
    buffer = _crash(started, location)
    _registry.pop(registry_key("metric", TASK_METRIC), None)
    try:
        final = eval_retry(
            started.location, log_dir=log_dir.as_posix(), incomplete_action="error"
        )[0]
    finally:
        buffer.cleanup()

    # recovery rebuilt the task-file metric, so it finalized the log
    assert final.status == "success"
    assert final.location is not None and "-recovered" in final.location
    assert final.results is not None


# --- rescoring -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["2t", "3t"])
def test_rescore_with_callers_scorers_rebuilds_log_metrics_untrusted(
    name: str, task_file: Path, imports: Path, untrusted_models: list[str]
) -> None:
    log = _fixture(name, task_file)
    error, message = _expected_error(name)

    with pytest.raises(error) as ex:
        score(
            log,
            counting_scorer(),
            action="overwrite",
            model="mockllm/model",
        )

    assert message in str(ex.value)
    assert str(ex.value).endswith(SCORE_OPT_IN)
    assert scored_samples == []
    assert _imported(imports) == [] and untrusted_models == []

    # the caller's own metrics replace the log's
    rescored = score(
        log,
        counting_scorer(),
        metrics=[accuracy()],
        action="overwrite",
        model="mockllm/model",
    )
    assert rescored.results is not None


@pytest.mark.parametrize("name", ["2s", "3s"])
def test_rescore_overwrite_ignores_replaced_scorer_metrics(
    name: str, task_file: Path, imports: Path, untrusted_models: list[str]
) -> None:
    rescored = score(
        _fixture(name, task_file),
        counting_scorer(),
        action="overwrite",
        model="mockllm/model",
    )

    assert rescored.results is not None
    assert _imported(imports) == [] and untrusted_models == []


@pytest.mark.parametrize("scorer", [None, "counting_scorer"])
async def test_score_cli_trusts_log_metrics_only_with_log_scorers(
    scorer: str | None,
    tmp_path: Path,
    untrusted_models: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._cli import score as score_cli

    monkeypatch.setattr(score_cli, "print_results", lambda *args, **kwargs: None)
    log = _fixture("3t", tmp_path)
    log.eval.scorers = [
        EvalScorer(
            name="counting_scorer", metrics=[EvalMetricDefinition(name="accuracy")]
        )
    ]
    input_file = tmp_path / "input.eval"
    await write_eval_log_async(log, input_file.as_posix())

    run = score_cli.score(
        log_dir=tmp_path.as_posix(),
        log_file=input_file.as_posix(),
        scorer=scorer,
        s=(),
        metric=None,
        overwrite=False,
        action="overwrite",
        log_level=None,
        output_file=(tmp_path / "output.eval").as_posix(),
        model="mockllm/model",
    )

    if scorer is None:
        # the log's own scorers: its metric options are rebuilt as recorded
        await run
        assert untrusted_models == [UNTRUSTED_URL]
        assert sorted(scored_samples) == [1, 2]
    else:
        with pytest.raises(DisallowedRegistryArg, match="option 'option': a model"):
            await run
        assert untrusted_models == []
        assert scored_samples == []


async def test_rescore_with_log_scorers_trusts_metric_options(
    task_file: Path, imports: Path, untrusted_models: list[str]
) -> None:
    log = _fixture("3t", task_file)
    rescored = await score_async(
        log,
        [match()],
        action="overwrite",
        model="mockllm/model",
        _log_scorers=True,
    )
    assert rescored.results is not None
    assert untrusted_models == [UNTRUSTED_URL]

    # a missing task-level metric still fails, without importing the task file
    with pytest.raises(LookupError, match=TASK_METRIC):
        await score_async(
            _fixture("2t", task_file),
            [match()],
            action="overwrite",
            model="mockllm/model",
            _log_scorers=True,
        )
    assert _imported(imports) == []
