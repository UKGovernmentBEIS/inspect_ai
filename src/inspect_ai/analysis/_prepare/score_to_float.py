from typing import Sequence

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

        # Apply value_to_float function to each specified column
        df_copy = df.copy()
        for col in column_list:
            df_copy[col] = df_copy[col].apply(value_to_float)

        return df_copy

    return transform
