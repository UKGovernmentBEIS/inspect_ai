from typing import TYPE_CHECKING, Sequence

from .._dataframe.util import verify_prerequisites
from .operation import Operation

if TYPE_CHECKING:
    import pandas as pd


def prepare(
    df: "pd.DataFrame", operation: Operation | Sequence[Operation]
) -> "pd.DataFrame":
    """Prepare a data frame for analysis using one or more transform operations.

    Args:
       df: Input data frame.
       operation: `Operation` or sequence of operations to apply.
    """
    verify_prerequisites()

    operation = operation if isinstance(operation, Sequence) else [operation]
    for op in operation:
        df = op(df)
    return df
