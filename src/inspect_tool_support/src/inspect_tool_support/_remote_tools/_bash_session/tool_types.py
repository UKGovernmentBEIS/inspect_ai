from typing import Literal

from pydantic import BaseModel, RootModel


class BashBaseParams(BaseModel):
    session_name: str


class CommandParams(BashBaseParams):
    command: str


class RestartParams(BashBaseParams):
    restart: Literal[True]


class BashParams(RootModel[CommandParams | RestartParams]):
    pass


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashCommandResult(BaseModel):
    status: int
    stdout: str
    stderr: str
