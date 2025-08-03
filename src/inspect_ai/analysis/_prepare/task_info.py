from typing import cast

from .operation import Operation


def task_info(
    display_names: dict[str, str],
    task_name_column: str = "task_name",
    task_display_name_column: str = "task_display_name",
) -> Operation:
    """Amend data frame with task display name.

    Maps task names to task display names for plotting (e.g. "gpqa_diamond" -> "GPQA Diamond")

    If no mapping is provided for a task then name will come from the `display_name` attribute of
    the `Task` (or failing that from the registered name of the `Task`).

    Args:
        display_names: Mapping of task log names (e.g. "gpqa_diamond") to task display names (e.g. "GPQA Diamond").
        task_name_column: Column to draw the task name from (defaults to "task_name").
        task_display_name_column: Column to populate with the task display name (defaults to "task_display_name")
    """
    import pandas as pd

    # function to resolve display name mappings
    def task_display_name(row: pd.Series) -> str:  # type: ignore[type-arg]
        if task_name_column not in row.keys():
            raise ValueError(f"The data frame has no column named '{task_name_column}'")

        # map task names to display names
        task_name = row[task_name_column]
        for k, v in display_names.items():
            if k == task_name:
                return v

        # none found, reflect any existing column value or fallback to task_name
        return cast(str, row.get(task_display_name_column, default=task_name))

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        df[task_display_name_column] = df.apply(task_display_name, axis=1)
        return df

    return transform
