from typing import Literal, TypeAlias

from pydantic import BaseModel, RootModel


class BashBaseParams(BaseModel):
    session_name: str
    model_config = {"extra": "forbid"}


class InteractParams(BashBaseParams):
    wait_for_output: int
    """
    Maximum time (in seconds) to wait for any output. If no output is received
    within this period, the function will return an empty string.
    """
    idle_timeout: float
    input: str | None = None


class RestartParams(BashBaseParams):
    restart: Literal[True]


class BashParams(RootModel[InteractParams | RestartParams]):
    pass


class NewSessionResult(BaseModel):
    session_name: str


BashRestartResult: TypeAlias = str


InteractResult: TypeAlias = str
