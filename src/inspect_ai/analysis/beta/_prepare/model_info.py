from typing import Dict

import pandas as pd
from pydantic import BaseModel

from inspect_ai.analysis.beta._dataframe.model_data.model_data import read_model_info
from inspect_ai.analysis.beta._prepare.operation import Operation


class ModelInfo(BaseModel):
    """Model information and metadata"""

    family: str
    model: str
    model_display_name: str | None = None
    family_display_name: str | None = None
    version: str | None = None
    release_date: str | None = None


def model_info(
    model_info: Dict[str, ModelInfo] | None = None,
) -> Operation:
    builtin_model_info = read_model_info()
    resolved_model_info = builtin_model_info | (model_info or {})

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        # Add columns from ModelInfo for each row based on the 'model' column
        fields = [
            "family_display_name",
            "model_display_name",
            "snapshot",
            "release_date",
            "knowledge_cutoff_date",
        ]

        # Ensure all fields are present in the DataFrame
        for field in fields:
            df[field] = None

        for idx in df.index:
            model = df.loc[idx, "model"]
            model_data = resolved_model_info.get(str(model))
            if model_data is not None:
                for field in fields:
                    df.loc[idx, field] = getattr(model_data, field, None)

        return df

    return transform
