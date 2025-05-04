from dataclasses import dataclass, field

from ..extract import input_as_str, list_as_str, score_values
from .columns import Column, Columns


@dataclass
class SampleColumns:
    eval: Columns | None = field(default=None)
    sample: Columns | None = field(default=None)


SampleSummaryDefault: Columns = {
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

SampleDefault = SampleColumns(
    eval={"eval_id": Column("eval.eval_id", required=True)},
    sample=SampleSummaryDefault,
)
