from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd


class Operation(Protocol):
    def __call__(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """Operation to transform a data frame for analysis.

        Args:
            df: Input data frame.
        """
        ...
