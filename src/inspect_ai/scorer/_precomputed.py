import json
from typing import Any, Literal

from inspect_ai._util.file import file
from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._metrics.accuracy import accuracy
from ._metrics.std import stderr
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[accuracy(), stderr()])
def precomputed_scores(
    scores: str, on_missing: Literal["unscored", "error"] = "unscored"
) -> Scorer:
    """Scorer that applies scores computed outside of Inspect.

    Reads scores from a file and applies them to samples by id, for
    example to attach human ratings to an existing log using the
    `score()` function or the `inspect score` command. Samples with no
    matching record are left unscored, or fail the eval if `on_missing`
    is "error". Records matching no sample are always ignored.

    The file must contain a list of records with an `id` field matching
    a sample id, a `value` field with the score value, and optionally
    `epoch`, `answer`, `explanation`, and `metadata` fields (other
    fields are ignored). Records without an `epoch` apply to every
    epoch of the sample, and a record with a matching `epoch` takes
    precedence over one without.

    Supported formats are JSON (an array of objects) and JSON Lines
    (`.jsonl`, one object per line).

    To score with metrics other than the default accuracy and stderr,
    either pass `metrics` to `score()` or wrap this scorer in your own
    `@scorer`-decorated factory:

    ```python
    @scorer(metrics={"helpful": [mean()], "harmless": [mean()]})
    def human_rubric() -> Scorer:
        return precomputed_scores("ratings.json")
    ```

    Args:
        scores: Path to the scores file. Can be a local filesystem path
            or a path to an S3 bucket (e.g. "s3://my-bucket/scores.json").
        on_missing: What to do with a sample that has no matching record.
            "unscored" (the default) leaves it unscored, so metrics are
            computed over the matched samples only. "error" raises,
            for a scores file intended to cover every sample.
    """
    if on_missing not in ("unscored", "error"):
        raise ValueError(
            f"Invalid on_missing value '{on_missing}' (expected 'unscored' or 'error')"
        )

    lookup = _read_scores_file(scores)

    async def score(state: TaskState, target: Target) -> Score | None:
        found = lookup.get((str(state.sample_id), state.epoch))
        if found is None:
            found = lookup.get((str(state.sample_id), None))
        if found is None and on_missing == "error":
            raise ValueError(
                f"No score record in {scores} for sample id "
                f"'{state.sample_id}' (epoch {state.epoch})"
            )
        return found.model_copy(deep=True) if found is not None else None

    return score


def _read_scores_file(scores_file: str) -> dict[tuple[str, int | None], Score]:
    with file(scores_file, "r") as f:
        if scores_file.lower().endswith(".jsonl"):
            records = [json.loads(line) for line in f if line.strip()]
        else:
            records = json.load(f)

    if not isinstance(records, list):
        raise ValueError(
            f"Scores file {scores_file} must contain a list of score records"
        )

    lookup: dict[tuple[str, int | None], Score] = {}
    for record in records:
        key, score = _score_from_record(record, scores_file)
        if key in lookup:
            id, epoch = key
            raise ValueError(
                f"Duplicate score record in {scores_file} for sample id '{id}'"
                + (f" and epoch {epoch}" if epoch is not None else "")
            )
        lookup[key] = score
    return lookup


def _score_from_record(
    record: Any, scores_file: str
) -> tuple[tuple[str, int | None], Score]:
    if not isinstance(record, dict):
        raise ValueError(
            f"Score records in {scores_file} must be objects (found {record!r})"
        )
    for required in ("id", "value"):
        if required not in record:
            raise ValueError(
                f"Score record {record!r} in {scores_file} has no '{required}' field"
            )
    epoch = record.get("epoch")
    if epoch is not None and not isinstance(epoch, int):
        raise ValueError(
            f"Score record {record!r} in {scores_file} has a non-integer 'epoch'"
        )
    score = Score(
        value=record["value"],
        answer=record.get("answer"),
        explanation=record.get("explanation"),
        metadata=record.get("metadata"),
    )
    return (str(record["id"]), epoch), score
