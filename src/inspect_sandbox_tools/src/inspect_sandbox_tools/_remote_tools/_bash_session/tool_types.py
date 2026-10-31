from typing import Literal, TypeAlias

from pydantic import BaseModel, RootModel

from ..._util.user_switch import RunAs


class BashBaseParams(BaseModel):
    session_name: str
    owner: str | None = None
    """The user a bound shell was created as. Required for a bound shell and
    refused for any other: the server answers only when it matches the shell."""
    model_config = {"extra": "forbid"}


class InteractParams(BashBaseParams):
    wait_for_output: int
    """
    Maximum time (in seconds) to wait for any output. If no output is received
    within this period, the function will return an empty string.
    """
    idle_timeout: float
    max_output_bytes: int | None = None
    """
    Maximum response size allowed by the host. The sandbox keeps the returned
    shell output below this value before JSON-RPC serialization.
    """
    input: str | None = None


class RestartParams(BashBaseParams):
    restart: Literal[True]


class BashParams(RootModel[InteractParams | RestartParams]):
    pass


class NewSessionResult(BaseModel):
    session_name: str


class NewSessionParams(BaseModel):
    """Parameters for bash_session_new_session."""

    user: str | RunAs | None = None
    """User to run as: a username, or the sandbox default user's identity as
    captured by the host. Switching requires the server to run as root, unless
    the server already runs as that identity."""
    bind: bool = False
    """Bind the shell to `user`, which must be a username: the shell gets a name
    that no other server issues, and serves only requests whose `owner` is that
    user."""
    model_config = {"extra": "forbid"}


BashRestartResult: TypeAlias = str


InteractResult: TypeAlias = str
