import os
import tempfile
from enum import StrEnum

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log, recompute_metrics, write_eval_log
from inspect_ai.log._log import CategoricalSchema
from inspect_ai.scorer import (
    Score,
    Scorer,
    Target,
    categorical,
    category_rate,
    frequency,
    scorer,
)
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._rehydrate import (
    _categorical_enum,
    detect_value_schema,
    rehydrate_value,
)
from inspect_ai.solver import TaskState


class Verdict(StrEnum):
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


class Sabotage(StrEnum):
    NONE = "none"
    SUBTLE = "subtle"
    OVERT = "overt"


def ss(v) -> SampleScore:
    return SampleScore(score=Score(value=v))


# ---------------------------------------------------------------------------
# frequency() / category_rate() unit tests
# ---------------------------------------------------------------------------


def test_frequency_infers_strenum_categories() -> None:
    result = frequency()([ss(Verdict.YES)] * 3 + [ss(Verdict.NO)])
    assert result == {"yes": 0.75, "no": 0.25, "unsure": 0.0}


def test_frequency_explicit_categories() -> None:
    result = frequency(categories=Verdict)([ss("yes"), ss("yes"), ss("no")])
    assert result == {
        "yes": pytest.approx(2 / 3),
        "no": pytest.approx(1 / 3),
        "unsure": 0.0,
    }


def test_frequency_relaxed_inference_with_stray_string() -> None:
    result = frequency()([ss(Verdict.YES), ss(Verdict.NO), ss("weird")])
    assert result["unsure"] == 0.0
    assert result["weird"] == pytest.approx(1 / 3)


def test_frequency_normalize_false() -> None:
    result = frequency(normalize=False)([ss(Verdict.YES)] * 3 + [ss(Verdict.NO)])
    assert result == {"yes": 3.0, "no": 1.0, "unsure": 0.0}


def test_frequency_rejects_dict_scores() -> None:
    with pytest.raises(TypeError, match="dict-valued"):
        frequency()([ss({"k": Verdict.YES})])


def test_frequency_rejects_list_scores() -> None:
    with pytest.raises(TypeError, match="list-valued"):
        frequency()([ss([Verdict.YES, Verdict.NO])])


def test_category_rate_named_by_category() -> None:
    result = category_rate(Verdict.YES)([ss(Verdict.YES), ss(Verdict.NO)])
    assert result == {"yes": 0.5}


def test_category_rate_rejects_dict_scores() -> None:
    with pytest.raises(TypeError, match="dict-valued"):
        category_rate("yes")([ss({"k": "yes"})])


def test_categorical_resolves_enum_to_list() -> None:
    from inspect_ai._util.registry import registry_params

    [m] = categorical(Verdict)
    assert registry_params(m)["categories"] == ["yes", "no", "unsure"]


# ---------------------------------------------------------------------------
# Score.value StrEnum preservation
# ---------------------------------------------------------------------------


def test_score_preserves_strenum_instance() -> None:
    s = Score(value=Verdict.YES)
    assert isinstance(s.value, Verdict)
    assert s.model_dump()["value"] == "yes"


def test_score_preserves_strenum_in_dict() -> None:
    s = Score(value={"k": Verdict.NO})
    assert isinstance(s.value["k"], Verdict)


# ---------------------------------------------------------------------------
# Rehydration helpers
# ---------------------------------------------------------------------------


def test_detect_value_schema_scalar() -> None:
    schema = detect_value_schema([Score(value=Verdict.YES)])
    assert isinstance(schema, CategoricalSchema)
    assert schema.categories == ["yes", "no", "unsure"]


def test_detect_value_schema_dict() -> None:
    schema = detect_value_schema([Score(value={"sab": Sabotage.NONE, "loss": 0.5})])
    assert isinstance(schema, dict)
    assert set(schema) == {"sab"}
    assert schema["sab"].categories == ["none", "subtle", "overt"]


def test_detect_value_schema_none_for_numeric() -> None:
    assert detect_value_schema([Score(value=0.5)]) is None
    assert detect_value_schema([Score(value={"k": 1})]) is None


def test_categorical_enum_cached() -> None:
    e1 = _categorical_enum(("a", "b"))
    e2 = _categorical_enum(("a", "b"))
    assert e1 is e2
    assert isinstance(e1("a"), StrEnum)


def test_rehydrate_scalar() -> None:
    schema = CategoricalSchema(categories=["yes", "no", "unsure"])
    v = rehydrate_value("yes", schema)
    assert isinstance(v, StrEnum)
    assert v == "yes"
    assert [str(m.value) for m in type(v)] == ["yes", "no", "unsure"]


def test_rehydrate_value_not_in_domain() -> None:
    schema = CategoricalSchema(categories=["yes", "no"])
    v = rehydrate_value("maybe", schema)
    assert v == "maybe"
    assert not isinstance(v, StrEnum)


def test_rehydrate_dict() -> None:
    schema = {"sab": CategoricalSchema(categories=["none", "subtle", "overt"])}
    v = rehydrate_value({"sab": "subtle", "loss": 0.5}, schema)
    assert isinstance(v["sab"], StrEnum)
    assert v["loss"] == 0.5


# ---------------------------------------------------------------------------
# End-to-end round-trip: eval -> write -> read -> recompute
# ---------------------------------------------------------------------------


@scorer(metrics=categorical(Verdict))
def _verdict_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        idx = (hash((state.sample_id, state.epoch))) % 3
        return Score(value=list(Verdict)[idx])

    return score


@scorer(metrics={"*": categorical()})
def _behaviour_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        idx = (hash((state.sample_id, state.epoch))) % 3
        return Score(
            value={"sab": list(Sabotage)[idx], "aware": list(Verdict)[(idx + 1) % 3]}
        )

    return score


def _metrics_snapshot(log) -> dict[str, dict[str, float]]:
    return {
        s.name: {k: round(v.value, 6) for k, v in s.metrics.items()}
        for s in log.results.scores
    }


def test_categorical_recompute_round_trip() -> None:
    task = Task(
        dataset=[Sample(input=f"q{i}") for i in range(20)],
        scorer=[_verdict_scorer(), _behaviour_scorer()],
        epochs=3,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]
        assert log.status == "success"

        # value_schema was recorded for both scorers
        assert log.eval.scorers is not None
        schemas = {s.name: s.value_schema for s in log.eval.scorers}
        assert isinstance(schemas["_verdict_scorer"], CategoricalSchema)
        assert schemas["_verdict_scorer"].categories == ["yes", "no", "unsure"]
        assert isinstance(schemas["_behaviour_scorer"], dict)
        assert set(schemas["_behaviour_scorer"]) == {"sab", "aware"}

        before = _metrics_snapshot(log)

        # all enum members reported (including any zero-counts)
        assert set(before["_verdict_scorer"]) == {"yes", "no", "unsure"}
        assert set(before["sab"]) == {"none", "subtle", "overt"}

        # round-trip through disk
        path = os.path.join(log_dir, "roundtrip.eval")
        write_eval_log(log, path)
        reloaded = read_eval_log(path)

        # values are plain strings on disk; rehydration must restore semantics
        assert isinstance(reloaded.samples[0].scores["_verdict_scorer"].value, str)
        assert not isinstance(
            reloaded.samples[0].scores["_verdict_scorer"].value, StrEnum
        )

        recompute_metrics(reloaded)
        after = _metrics_snapshot(reloaded)

    assert before == after
