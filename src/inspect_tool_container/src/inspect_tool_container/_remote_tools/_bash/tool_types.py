from typing import Literal

from pydantic import BaseModel, RootModel


class CommandParams(BaseModel):
    command: str


class RestartParams(BaseModel):
    restart: Literal[True]


class BashParams(RootModel[CommandParams | RestartParams]):
    pass


class BashRestartResult(BaseModel):
    pass


class BashCommandResult(BaseModel):
    status: int
    stdout: str
    stderr: str
