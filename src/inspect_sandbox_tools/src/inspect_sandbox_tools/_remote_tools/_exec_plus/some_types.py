from pydantic import BaseModel, Field


class ExecPlusStartRequest(BaseModel):
    cmd: list[str]
    input: str | bytes | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class ExecPlusStartResponse(BaseModel):
    session_name: str


class ExecPlusPollRequest(BaseModel):
    session_name: str
    wait_for_output: int = 30
    idle_timeout: float = 0.5


class ExecPlusPollResponse(BaseModel):
    stdout: str
    stderr: str
    completed: bool = False
    exit_code: int | None = None


