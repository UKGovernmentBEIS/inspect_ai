"""Tests for `zero_samples()` and the `empty_attempt()` solver."""

import math
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Epochs, Task, eval, task
from inspect_ai._util.error import EvalError
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.event import ModelEvent
from inspect_ai.log import (
    EvalLog,
    ProvenanceData,
    exclude_samples,
    zero_samples,
)
from inspect_ai.log._log import EvalMetricDefinition, EvalSampleLimit
from inspect_ai.scorer import Score, Target, accuracy, includes, match, scorer
from inspect_ai.scorer._metric import score_is_excluded
from inspect_ai.scorer._scorer import Scorer
from inspect_ai.solver import (
    Generate,
    Solver,
    SolverSpec,
    TaskState,
    generate,
    solver,
)
from inspect_ai.solver._empty import empty_attempt

# mockllm's default output, which both scorers count correct
TARGET = "Default output from mockllm/model"


@solver
def mark_setup() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.metadata["setup_ran"] = True
        return state

    return solve


@solver
def fail_on_sample(sample_id: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == sample_id:
            raise RuntimeError("sample failed")
        return await generate(state)

    return solve


@scorer(metrics=[accuracy()])
def none_when_empty() -> Scorer:
    """Scores `C` for a non-empty completion and nothing for an empty one."""

    async def score(state: TaskState, target: Target) -> Score | None:
        return Score(value="C") if state.output.completion else None

    return score


@task
def zero_task(
    ids: tuple[Any, ...] = ("a", "b", "c", "d"),
    epochs: int = 1,
    fail: str | None = None,
    conditional: bool = False,
) -> Task:
    return Task(
        dataset=MemoryDataset([Sample(id=id, input="hi", target=TARGET) for id in ids]),
        setup=mark_setup(),
        solver=fail_on_sample(fail) if fail else generate(),
        scorer=[match(), none_when_empty() if conditional else includes()],
        epochs=Epochs(epochs),
    )


def _run(tmp_path: Path, task: Task, **kwargs: Any) -> EvalLog:
    log = eval(
        task,
        model="mockllm/model",
        log_dir=tmp_path.as_posix(),
        display="none",
        **kwargs,
    )[0]
    assert log.samples is not None
    return log


def _empty(tmp_path: Path, task: Task, **kwargs: Any) -> EvalLog:
    return _run(tmp_path / "empty", task, solver=empty_attempt(), **kwargs)


def _provenance(reason: str = "the agent was handed the answer") -> ProvenanceData:
    return ProvenanceData(author="operator", reason=reason)


def _sample(log: EvalLog, id: Any, epoch: int = 1) -> Any:
    return next(s for s in log.samples or [] if s.id == id and s.epoch == epoch)


def _accuracy(log: EvalLog) -> float:
    assert log.results is not None
    return log.results.scores[0].metrics["accuracy"].value


def _refused(log: EvalLog, empty: EvalLog, samples: list[Any], match: str) -> None:
    before = log.model_dump_json()
    with pytest.raises(ValueError, match=match):
        zero_samples(log, empty, samples, _provenance())
    assert log.model_dump_json() == before


def test_zero_samples(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task(), sample_id=["a", "b"])
    assert _accuracy(log) == 1.0

    # the empty attempt ran Task.setup and nothing else
    assert empty.eval.solver == "inspect_ai/empty_attempt"
    for sample in empty.samples or []:
        assert sample.metadata["setup_ran"] is True
        assert not any(isinstance(e, ModelEvent) for e in sample.events)
        assert {name: s.value for name, s in (sample.scores or {}).items()} == {
            "match": "I",
            "includes": "I",
        }

    target = _sample(log, "a")
    originals = {name: s.model_copy(deep=True) for name, s in target.scores.items()}
    transcript = target.model_dump_json(include={"messages", "output", "error"})
    provenance = _provenance()

    zero_samples(log, empty, ["a"], provenance)

    verdicts = _sample(empty, "a").scores
    for name, original in originals.items():
        zeroed = target.scores[name]
        assert zeroed.value == verdicts[name].value == "I"
        assert zeroed.answer == verdicts[name].answer
        assert zeroed.explanation == verdicts[name].explanation
        assert zeroed.reason == "zeroed"
        assert zeroed.history[0].value == original.value == "C"
        assert zeroed.history[-1].provenance == provenance
    assert target.model_dump_json(include={"messages", "output", "error"}) == (
        transcript
    )
    assert _sample(log, "b").scores["match"].value == "C"
    assert _accuracy(log) == 0.75


def test_zero_samples_errored_target(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task(fail="b"), fail_on_error=False)
    empty = _empty(tmp_path, zero_task(fail="b"), sample_id="b")
    errored = _sample(log, "b")
    assert errored.error is not None and not errored.scores

    zero_samples(log, empty, ["b"], _provenance())

    assert {name: s.value for name, s in errored.scores.items()} == {
        "match": "I",
        "includes": "I",
    }
    assert all(s.reason == "zeroed" for s in errored.scores.values())
    assert errored.error is not None


def test_zero_samples_epochs(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task(epochs=2))
    empty = _empty(tmp_path, zero_task(epochs=2), sample_id=["a", "b"])
    assert len(empty.samples or []) == 4

    zero_samples(log, empty, [("a", 1), ("b", 2)], _provenance())

    zeroed = {
        (s.id, s.epoch)
        for s in log.samples or []
        if (s.scores or {})["match"].reason == "zeroed"
    }
    assert zeroed == {("a", 1), ("b", 2)}

    # a target epoch the empty-attempt log lacks
    one_epoch = _empty(tmp_path, zero_task(epochs=1), sample_id="a")
    _refused(log, one_epoch, [("a", 2)], r"'a' \(epoch 2\): the empty-attempt log has")


def test_zero_samples_bare_solver_name(tmp_path: Path) -> None:
    """`inspect eval --solver empty_attempt` records the bare name."""
    log = _run(tmp_path, zero_task())
    empty = _run(
        tmp_path / "empty",
        zero_task(),
        solver=SolverSpec("empty_attempt"),
        sample_id="a",
    )
    assert empty.eval.solver == "empty_attempt"

    zero_samples(log, empty, ["a"], _provenance())

    assert _sample(log, "a").scores["match"].reason == "zeroed"


def test_zero_samples_refuses_empty_attempt_log(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task(), sample_id="a")

    _refused(log, empty.model_copy(update={"status": "error"}), ["a"], "'error'")
    _refused(log, empty.model_copy(update={"samples": None}), ["a"], "no samples")
    # a plain run of the task is not an empty attempt
    _refused(log, log, ["a"], "solver None")

    def header(**update: Any) -> EvalLog:
        other = empty.model_copy(deep=True)
        for key, value in update.items():
            setattr(other.eval, key, value)
        return other

    _refused(log, header(solver="generate"), ["a"], "solver 'generate'")
    _refused(log, header(task="other_task"), ["a"], "of the task 'other_task'")
    scorers = empty.eval.scorers or []
    _refused(log, header(scorers=scorers[:1]), ["a"], "are not those of the log")
    _refused(log, header(scorers=scorers[::-1]), ["a"], "are not those of the log")
    no_scorers = log.model_copy(deep=True)
    no_scorers.eval.scorers = None
    _refused(no_scorers, header(scorers=None), ["a"], "names no scorer")


def test_zero_samples_verdict_rule(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task())

    def verdicts(**scores: Any) -> EvalLog:
        other = empty.model_copy(deep=True)
        _sample(other, "a").scores = {
            name: score if isinstance(score, Score) else Score(value=score)
            for name, score in scores.items()
        }
        return other

    errored = empty.model_copy(deep=True)
    _sample(errored, "a").error = EvalError(
        message="setup failed", traceback="", traceback_ansi=""
    )
    _refused(log, errored, ["a"], "the empty attempt errored: setup failed")
    limited = empty.model_copy(deep=True)
    _sample(limited, "a").limit = EvalSampleLimit(type="time", limit=1)
    _refused(log, limited, ["a"], "hit its time limit")

    missing = empty.model_copy(deep=True)
    missing.samples = [s for s in missing.samples or [] if s.id != "a"]
    _refused(log, missing, ["a"], "'a' \\(epoch 1\\): the empty-attempt log has no")

    _refused(log, verdicts(), ["a"], "no verdict")
    _refused(
        log, verdicts(match={"x": 0}, includes="I"), ["a"], "'match': a dict or list"
    )
    _refused(
        log, verdicts(match="I", includes=[0, 1]), ["a"], "'includes': a dict or list"
    )
    _refused(
        log,
        verdicts(
            match=Score.unscored(reason="grader_failed", explanation="no verdict"),
            includes="I",
        ),
        ["a"],
        "'match': an unscored value \\(reason 'grader_failed', explanation "
        "'no verdict'\\)",
    )
    cited = Score(
        value="I", metadata={"scanner_references": [{"type": "message", "id": "m1"}]}
    )
    _refused(log, verdicts(match=cited, includes="I"), ["a"], "transcript references")

    # the score-edit sentinel would keep the target's field instead of copying it
    for field in ("value", "answer", "explanation"):
        sentinel = Score(value="I").model_copy(update={field: "UNCHANGED"})
        _refused(
            log,
            verdicts(match=sentinel, includes="I"),
            ["a"],
            f"'match': the {field} is 'UNCHANGED'",
        )
    # ... including for a later target with no score, after a valid one
    scoreless = log.model_copy(deep=True)
    del _sample(scoreless, "b").scores["match"]
    later = empty.model_copy(deep=True)
    _sample(later, "b").scores["match"] = Score(value="UNCHANGED")
    _refused(
        scoreless, later, ["a", "b"], "'b' \\(epoch 1\\): score 'match': the value"
    )

    # an empty references list cites nothing
    uncited = Score(value="I", metadata={"scanner_references": []})
    zeroed = log.model_copy(deep=True)
    zero_samples(
        zeroed,
        verdicts(match=uncited, includes="I"),
        ["a"],
        _provenance(),
    )
    assert _sample(zeroed, "a").scores["match"].reason == "zeroed"

    # a solver-written score the empty attempt does not produce
    written = log.model_copy(deep=True)
    _sample(written, "a").scores["solver_key"] = Score(value=1)
    _refused(written, empty, ["a"], "'solver_key': the empty attempt does not")

    # every failing target is named in one error
    both = empty.model_copy(deep=True)
    for id in ("a", "b"):
        _sample(both, id).scores = {}
    with pytest.raises(ValueError) as error:
        zero_samples(log, both, ["a", "b"], _provenance())
    assert "'a' (epoch 1): no verdict" in str(error.value)
    assert "'b' (epoch 1): no verdict" in str(error.value)
    assert "excluded instead" in str(error.value)


def test_zero_samples_conditional_scorer(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task(conditional=True))
    empty = _empty(tmp_path, zero_task(conditional=True), sample_id="a")
    assert list(_sample(empty, "a").scores) == ["match"]

    _refused(log, empty, ["a"], "'none_when_empty': the empty attempt does not")


def test_zero_samples_refuses_integer_ids(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task(ids=(1, 2)))
    empty = _empty(tmp_path, zero_task(ids=(1, 2)), sample_id=1)

    _refused(log, empty, [1], "sample 1 \\(epoch 1\\): the id is an integer")


def test_zero_samples_twice(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task(), sample_id="a")
    zero_samples(log, empty, ["a"], _provenance())
    score = _sample(log, "a").scores["match"]
    history = len(score.history)

    zero_samples(log, empty, ["a"], _provenance("again"))

    assert len(score.history) == history + 1
    provenance = score.history[-1].provenance
    assert provenance is not None and provenance.reason == "again"


def test_zero_samples_empty_selectors_resolve_metrics(tmp_path: Path) -> None:
    """No selector edits nothing, but an unbuildable metric is still refused."""
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task(), sample_id="a")
    assert log.eval.scorers is not None
    log.eval.scorers[0].metrics = [EvalMetricDefinition(name="no_such_metric")]
    before = log.model_dump_json()

    with pytest.raises(LookupError, match="no_such_metric"):
        zero_samples(log, empty, [], _provenance())
    assert log.model_dump_json() == before


def test_zero_samples_stacks_with_exclusion(tmp_path: Path) -> None:
    log = _run(tmp_path, zero_task())
    empty = _empty(tmp_path, zero_task(), sample_id="a")
    exclude_samples(log, ["a"], _provenance())
    score = _sample(log, "a").scores["match"]
    assert score_is_excluded(score)

    zero_samples(log, empty, ["a"], _provenance())

    assert score.value == "I" and score.reason == "zeroed"
    assert [edit.reason for edit in score.history] == [None, "excluded", "zeroed"]
    assert not math.isnan(_accuracy(log))
