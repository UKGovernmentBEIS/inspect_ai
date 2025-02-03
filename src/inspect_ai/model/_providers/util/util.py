import os
from logging import getLogger

from inspect_ai._util.error import PrerequisiteError

logger = getLogger(__name__)


def model_base_url(base_url: str | None, env_vars: str | list[str]) -> str | None:
    if base_url:
        return base_url

    if isinstance(env_vars, str):
        env_vars = [env_vars]

    for env_var in env_vars:
        base_url = os.getenv(env_var, None)
        if base_url:
            return base_url

    return os.getenv("INSPECT_EVAL_MODEL_BASE_URL", None)


def environment_prerequisite_error(
    client: str, env_vars: str | list[str]
) -> PrerequisiteError:
    def fmt(key: str) -> str:
        return f"[bold][blue]{key}[/blue][/bold]"

    env_vars = [env_vars] if isinstance(env_vars, str) else env_vars
    if len(env_vars) == 1:
        env_vars_list = fmt(env_vars[0])
    else:
        env_vars_list = (
            ", ".join([fmt(env_bar) for env_bar in env_vars[:-1]])
            + ("," if len(env_vars) > 2 else "")
            + " or "
            + fmt(env_vars[-1])
        )

    return PrerequisiteError(
        f"ERROR: Unable to initialise {client} client\n\nNo {env_vars_list} defined in the environment."
    )
