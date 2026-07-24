import json
from pathlib import Path

import pytest

from inspect_ai import Task, eval, score
from inspect_ai._eval.score import resolve_scorers
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.scorer import Scorer, mean, precomputed_scores, scorer


def run_eval(epochs: int = 1) -> EvalLog:
    task = Task(
        dataset=[
            Sample(input="q1", target="a1", id="s1"),
            Sample(input="q2", target="a2", id="s2"),
            Sample(input="q3", target="a3", id=3),
        ],
        epochs=epochs,
    )
    return eval(task, model="mockllm/model")[0]


def sample_scores(log: EvalLog, score_name: str = "precomputed_scores"):
    assert log.samples is not None
    return {
        (sample.id, sample.epoch): sample.scores[score_name]
        for sample in log.samples
        if sample.scores and score_name in sample.scores
    }


def write_records(path: Path, records: list[dict]) -> str:
    path.write_text(json.dumps(records))
    return path.as_posix()


def test_precomputed_scores_json(tmp_path: Path) -> None:
    scores_file = write_records(
        tmp_path / "scores.json",
        [
            {
                "id": "s1",
                "value": 1,
                "answer": "yes",
                "explanation": "rated by human",
                "metadata": {"rater": "alice"},
            },
            {"id": 3, "value": 0},
        ],
    )

    log = score(run_eval(), precomputed_scores(scores_file))

    scores = sample_scores(log)
    assert set(scores) == {("s1", 1), (3, 1)}
    assert scores[("s1", 1)].value == 1
    assert scores[("s1", 1)].answer == "yes"
    assert scores[("s1", 1)].explanation == "rated by human"
    assert scores[("s1", 1)].metadata == {"rater": "alice"}
    assert scores[(3, 1)].value == 0

    assert log.results is not None
    assert log.results.scores[-1].metrics["accuracy"].value == 0.5


def test_precomputed_scores_jsonl(tmp_path: Path) -> None:
    scores_file = tmp_path / "scores.jsonl"
    scores_file.write_text(
        json.dumps({"id": "s1", "value": 1})
        + "\n"
        + json.dumps({"id": "s2", "value": 0.5})
    )

    log = score(run_eval(), precomputed_scores(scores_file.as_posix()))

    scores = sample_scores(log)
    assert scores[("s1", 1)].value == 1
    assert scores[("s2", 1)].value == 0.5


def test_precomputed_scores_csv(tmp_path: Path) -> None:
    scores_file = tmp_path / "scores.csv"
    scores_file.write_text(
        "id,epoch,value,answer,metadata\n"
        's1,,0.5,yes,"{""rater"": ""alice""}"\n'
        "3,1,C,,\n"
    )

    log = score(run_eval(), precomputed_scores(scores_file.as_posix()))

    scores = sample_scores(log)
    assert scores[("s1", 1)].value == 0.5
    assert scores[("s1", 1)].answer == "yes"
    assert scores[("s1", 1)].metadata == {"rater": "alice"}
    assert scores[(3, 1)].value == "C"
    assert scores[(3, 1)].answer is None


def test_precomputed_scores_epochs(tmp_path: Path) -> None:
    scores_file = write_records(
        tmp_path / "scores.json",
        [
            {"id": "s1", "value": 1},
            {"id": "s2", "value": 0},
            {"id": "s2", "epoch": 2, "value": 1},
        ],
    )

    log = score(run_eval(epochs=2), precomputed_scores(scores_file))

    scores = sample_scores(log)
    assert scores[("s1", 1)].value == 1
    assert scores[("s1", 2)].value == 1
    assert scores[("s2", 1)].value == 0
    assert scores[("s2", 2)].value == 1
    assert (3, 1) not in scores and (3, 2) not in scores


def test_precomputed_scores_custom_metrics(tmp_path: Path) -> None:
    scores_file = write_records(
        tmp_path / "scores.json",
        [
            {"id": "s1", "value": {"helpful": 1, "harmless": 0}},
            {"id": "s2", "value": {"helpful": 0, "harmless": 1}},
        ],
    )

    @scorer(metrics={"helpful": [mean()], "harmless": [mean()]})
    def human_rubric() -> Scorer:
        return precomputed_scores(scores_file)

    log = score(run_eval(), human_rubric())

    scores = sample_scores(log, "human_rubric")
    assert scores[("s1", 1)].value == {"helpful": 1, "harmless": 0}

    assert log.results is not None
    by_name = {s.name: s for s in log.results.scores}
    assert by_name["helpful"].metrics["mean"].value == 0.5
    assert by_name["harmless"].metrics["mean"].value == 0.5


def test_precomputed_scores_rescorable(tmp_path: Path) -> None:
    scores_file = write_records(tmp_path / "scores.json", [{"id": "s1", "value": 1}])

    log = score(run_eval(), precomputed_scores(scores_file))

    assert log.eval.scorers is not None
    header_scorer = log.eval.scorers[-1]
    assert header_scorer.name == "precomputed_scores"
    assert header_scorer.options == {"scores": scores_file}

    resolved = resolve_scorers(log)
    assert len(resolved) == 1


def test_precomputed_scores_invalid_records(tmp_path: Path) -> None:
    duplicate = write_records(
        tmp_path / "duplicate.json",
        [{"id": "s1", "value": 1}, {"id": "s1", "value": 0}],
    )
    with pytest.raises(ValueError, match="Duplicate"):
        precomputed_scores(duplicate)

    missing_value = write_records(tmp_path / "missing_value.json", [{"id": "s1"}])
    with pytest.raises(ValueError, match="'value'"):
        precomputed_scores(missing_value)

    missing_id = write_records(tmp_path / "missing_id.json", [{"value": 1}])
    with pytest.raises(ValueError, match="'id'"):
        precomputed_scores(missing_id)

    not_a_list = tmp_path / "not_a_list.json"
    not_a_list.write_text(json.dumps({"s1": 1}))
    with pytest.raises(ValueError, match="list"):
        precomputed_scores(not_a_list.as_posix())
