import pandas as pd

from ..util import LogPaths, verify_prerequisites


def events_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    verify_prerequisites()

    raise NotImplementedError("events_df has not been implemented yet.")
