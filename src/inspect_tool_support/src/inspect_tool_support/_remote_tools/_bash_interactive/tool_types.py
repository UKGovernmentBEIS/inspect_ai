from typing import Literal

from pydantic import BaseModel, RootModel


class BaseParams(BaseModel):
    session_name: str


class InteractParams(BaseParams):
    input_text: str | None = None
    idle_timeout: int
    """
    The number of seconds to wait without any new output arriving from the bash
    session. After this timeout, the currently collected data (if any) will be
    returned to the caller. Data may be returned before this timeout.
    """


class RestartParams(BaseParams):
    restart: Literal[True]


class BashInteractiveParams(RootModel[InteractParams | RestartParams]):
    pass


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class InteractResult(BaseModel):
    stdout: str
    stderr: str
