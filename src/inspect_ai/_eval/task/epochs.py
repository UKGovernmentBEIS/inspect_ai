from inspect_ai.scorer._reducer import ScoreReducers, create_reducers


class Epochs:
    """Task epochs.

    Number of epochs to repeat samples over and optionally one or more
    reducers used to combine scores from samples across epochs. If not
    specified the "mean" score reducer is used.
    """

    def __init__(self, epochs: int, reducer: ScoreReducers | None = None) -> None:
        """Task epochs.

        Args:
           epochs (int): Number of epochs
           reducer (ScoreReducers): One or more reducers used to combine
              scores from samples across epochs (defaults to "mean)
        """
        self.epochs = epochs
        self.reducer = create_reducers(reducer)
