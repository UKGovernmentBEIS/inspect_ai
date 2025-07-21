from functools import partial
from typing import Dict

import pandas as pd
from pydantic import BaseModel

from inspect_ai.analysis.beta._prepare.operation import Operation


class ModelInfo(BaseModel):
    """Model information and metadata"""

    family: str
    model: str
    model_short_name: str | None = None
    version: str | None = None
    release_date: str | None = None


def model_info(
    model_info: Dict[str, ModelInfo] | None = None,
) -> Operation:
    def transform(df: pd.DataFrame) -> pd.DataFrame:
        def get_model_field(model: str, field: str) -> str | None:
            """Retrieve a specific field from model info.

            This function can be expanded to handle complex logic like:
            - Loading data from external sources
            - Calling APIs or other functions
            - Complex data transformations
            """
            model_data = (model_info | {}).get(model)
            if model_data is None:
                return None

            # Example of where you could add complex logic:
            # if field == "family":
            #     return load_and_process_family_data(model)
            # elif field == "version":
            #     return call_version_api(model)

            return getattr(model_data, field, None)

        # Add columns from ModelInfo for each row based on the 'model' column
        for field in ["family", "model_short_name", "version", "release_date"]:
            df[field] = df["model"].map(partial(get_model_field, field=field))
        return df

    return transform
