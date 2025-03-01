from typing import Literal, Union

from pydantic import BaseModel, RootModel


class CommandParams(BaseModel):
    command: str


class RestartParams(BaseModel):
    restart: Literal[True]


class BashParams(RootModel[Union[CommandParams, RestartParams]]):
    pass


class BashResponse(BaseModel):
    status: int
    stdout: str
    stderr: str
