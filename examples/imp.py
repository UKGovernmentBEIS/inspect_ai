import functools
from typing import Callable

from pydantic import BaseModel, JsonValue

from inspect_ai.analysis.beta import EvalColumn, evals_df
from inspect_ai.log._log import EvalLog


class ReportConfig(BaseModel):
    pass


class ReportColumn(EvalColumn):
    def __init__(
        self,
        name: str,
        config: ReportConfig,
        extract: Callable[[ReportConfig, EvalLog], JsonValue],
        *,
        required: bool = False,
    ) -> None:
        super().__init__(
            name=name,
            path=functools.partial(extract, config),
            required=required,
        )


def read_value(config: ReportConfig, log: EvalLog) -> JsonValue:
    return 1


df = evals_df(
    "logs",
    columns=[ReportColumn("foo", ReportConfig(), read_value)],
)
print(df.head())
