from dataclasses import dataclass, field

from ..columns import Column, Columns
from ..extract import input_as_str, list_as_str, score_values


@dataclass
class SampleColumns:
    """Columns specification for samples data frame."""

    eval: Columns | None = field(default=None)
    """Columns from eval table (defaults to `eval_id`)."""

    sample: Columns | None = field(default=None)
    """Columns from samples (defaults to `SampleSummary`)"""


SampleSummary: Columns = {
    "id": Column("id", required=True, type=str),
    "epoch": Column("epoch", required=True),
    "input": Column("input", required=True, value=input_as_str),
    "target": Column("target", required=True, value=list_as_str),
    "metadata_*": Column("metadata"),
    "score_*": Column("scores", value=score_values),
    "model_usage": Column("model_usage"),
    "total_time": Column("total_time"),
    "working_time": Column("total_time"),
    "error": Column("error"),
    "limit": Column("limit"),
    "retries": Column("retries"),
}
"""Sample summary columns."""

SampleDefault = SampleColumns(
    eval={"eval_id": Column("eval.eval_id", required=True)},
    sample=SampleSummary,
)
"""Default columns to import for `samples_df()`."""
