from typing import Any, Sequence

from inspect_ai.analysis._prepare.operation import Operation
from inspect_ai.scorer._metric import ValueToFloat, value_to_float


def score_to_float(
    columns: str | Sequence[str], *, value_to_float: ValueToFloat = value_to_float()
) -> Operation:
    """Converts score columns to float values.

    For each column specified, this operation will convert the values to floats using the provided `value_to_float` function. The column value will be replaced with the float value.

    Args:
        columns: The name of the score column(s) to convert to float. This can be a single column name or a sequence of column names.
        value_to_float: Function to convert values to float. Defaults to the built-in `value_to_float` function.
    """
    import pandas as pd

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        # Ensure required columns exist
        column_list = [columns] if isinstance(columns, str) else columns
        for col in column_list:
            if col not in df.columns:
                raise ValueError(f"Column '{col}' not found in DataFrame")

        # Apply value_to_float function to each specified column. Score
        # columns from samples_df() are pyarrow-backed and use pd.NA for
        # missing values (e.g. samples from logs that didn't run this
        # scorer); pass these through as NaN rather than feeding them to
        # value_to_float() where `pd.NA == "C"` raises a TypeError.
        def to_float(v: Any) -> float:
            if pd.isna(v):
                return float("nan")
            return value_to_float(v)

        df_copy = df.copy()
        for col in column_list:
            df_copy[col] = df_copy[col].apply(to_float)

        return df_copy

    return transform
