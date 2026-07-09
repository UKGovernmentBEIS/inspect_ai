from pydantic import BaseModel, JsonValue


class ResumeReport(BaseModel):
    """Outcome of a checkpoint resume.

    Returned by ``Task.on_resume`` and surfaced as ``checkpointer().restored``.
    Inspect records this in the transcript but does NOT act on it: deciding
    whether and how to surface it to the model is the agent's responsibility.
    """

    transparent: bool = False
    """The task verified that nothing the model can observe changed on resume.
    A consuming agent should suppress any resume notice. (Injecting one is the
    only thing that would let the model tell it was resumed.)"""

    message: str | None = None
    """Suggested model-facing prose describing what changed and what to redo.
    Advisory: the consuming agent may render, replace, or ignore it. The
    framework cannot synthesize this because it cannot know task semantics."""

    data: dict[str, JsonValue] | None = None
    """Optional structured detail, recorded in the log and available to agent
    code that reads ``restored`` directly. Not shown to the model unless
    reflected in ``message``."""


def resolve_resume_report(
    value: ResumeReport | str | None,
) -> ResumeReport | None:
    """A bare ``str`` return is shorthand for ``ResumeReport(message=value)``."""
    if value is None:
        return None
    if isinstance(value, str):
        return ResumeReport(message=value)
    return value
