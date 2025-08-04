from inspect_ai.analysis._prepare.operation import Operation


def frontier(
    task_column: str = "task_name",
    date_column: str = "model_release_date",
    score_column: str = "score_headline_value",
    frontier_column: str = "frontier",
) -> Operation:
    """Add a frontier column to an eval data frame.

    Tranform operation to add a frontier column to a data frame based using a task, release date, and score.

    The frontier column will be True if the model was the top-scoring model on the task among all models available at the moment the model was released; otherwise it will be False.

    Args:
        task_column: The column in the data frame containing the task name (defaults to "task_name").
        date_column: The column in the data frame containing the model release date (defaults to "model_release_date").
        score_column: The column in the data frame containing the score (defaults to "score_headline_value").
        frontier_column: The column to create with the frontier value (defaults to "frontier").
    """
    import pandas as pd

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
        df[frontier_column] = False

        # Group by task_name and process each task
        for _, task_group in df.groupby(task_column):
            # Filter out models with missing release dates for frontier calculation
            task_group_with_dates = task_group.dropna(subset=[date_column])

            # For each release date, keep only the highest scoring model
            best_per_date = task_group_with_dates.dropna(subset=[score_column]).loc[
                task_group_with_dates.groupby(date_column)[score_column].idxmax()
            ]

            # Sort by model_release_date to process chronologically
            best_per_date = best_per_date.sort_values(date_column)

            # Track the highest score seen so far
            highest_score = float("-inf")
            frontier_indices = []

            for idx, row in best_per_date.iterrows():
                current_score = row[score_column]

                # If this is a new high score, it's on the frontier
                if current_score > highest_score:
                    highest_score = current_score
                    frontier_indices.append(idx)

            # Mark frontier models
            df.loc[frontier_indices, frontier_column] = True

        return df

    return transform
