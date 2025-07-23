import pandas as pd

from inspect_ai.analysis.beta._prepare.operation import Operation


def frontier(
    task_column: str = "task_name",
    date_column: str = "model_release_date",
    score_column: str = "score_headline_value",
) -> Operation:
    def transform(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        # Ensure required columns exist
        required_columns = [task_column, date_column, score_column]
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in DataFrame")

        # Initialize frontier column
        df = df.copy()
        df["frontier"] = False

        # Group by task_name and process each task
        for _, task_group in df.groupby(task_column):
            # Filter out models with missing release dates for frontier calculation
            task_group_with_dates = task_group.dropna(subset=[date_column])

            # Sort by model_release_date to process chronologically
            task_group_with_dates = task_group_with_dates.sort_values(date_column)

            # Track the highest score seen so far
            highest_score = float("-inf")
            frontier_indices = []

            for idx, row in task_group_with_dates.iterrows():
                current_score = row[score_column]

                # Skip if score is NaN
                if pd.isna(current_score):
                    continue

                # If this is a new high score, it's on the frontier
                if current_score > highest_score:
                    highest_score = current_score
                    frontier_indices.append(idx)

            # Mark frontier models
            df.loc[frontier_indices, "frontier"] = True

        return df

    return transform
