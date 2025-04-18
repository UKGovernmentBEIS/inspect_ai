from typing import Literal

from pydantic import BaseModel, RootModel


class BashBaseParams(BaseModel):
    session_name: str


class InputParams(BashBaseParams):
    command: str | None = None


class RestartParams(BashBaseParams):
    restart: Literal[True]


class BashParams(RootModel[InputParams | RestartParams]):
    pass


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashInputResult(BaseModel):
    stdout: str
    stderr: str
