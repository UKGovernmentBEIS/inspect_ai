"""Operator targets: named agents in a running sample that ``inspect ctl`` can act on.

Code running in a sample registers a group of named agents with
:func:`operator_group`. The control server lists them
(``GET /evals/{id}/sample/agents``) and sends them ``message``, ``pause``,
``resume`` and ``stop`` (``POST /evals/{id}/sample/agent/{action}``).
Inspect knows nothing of what an agent or a group is: the registrant
implements the actions.

The server calls a registrant's methods synchronously from its handlers.
They run on the eval's loop, so an action is atomic with respect to the
agents it acts on, but in the server's task and context, not the sample's: a
registrant that needs its own context enters it itself. Methods must not
await or do work proportional to a conversation's size, and their outcomes
and infos carry no agent-written text (names, lifecycle words, statuses and
fixed sentences only), since the control channel shows them to the operator
as they are.
"""

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Literal, NamedTuple, Protocol, get_args

OperatorAction = Literal["message", "pause", "resume", "stop"]
"""An action the operator can send to an agent or a group."""

OPERATOR_ACTIONS: tuple[OperatorAction, ...] = get_args(OperatorAction)


@dataclass(frozen=True)
class OperatorOutcome:
    """The result of one operator action."""

    changed: bool
    """Whether the action changed anything (``False`` for a repeat)."""

    detail: str
    """One line for the operator, with no agent-written text."""

    refused: str | None = None
    """Why the action cannot apply, if it cannot (the route answers 409)."""


@dataclass(frozen=True)
class OperatorAgentInfo:
    """What the operator sees of one agent."""

    name: str
    state: str
    """The registrant's lifecycle word, such as pending, running or ended."""

    status: str | None
    """How the agent ended, once it has."""

    activity: str
    """What the agent is doing, such as in_turn, between_turns or held."""

    paused: bool
    """Whether a pause is in effect for the agent, whether it is held yet or not."""

    actions: dict[OperatorAction, str | None]
    """Each action: ``None`` when it would be accepted now, otherwise why not."""


class OperatorAgent(Protocol):
    """One named agent the operator can act on."""

    def info(self) -> OperatorAgentInfo: ...

    def message(
        self, text: str, *, interrupt: bool, dry_run: bool
    ) -> OperatorOutcome: ...

    def pause(self, *, dry_run: bool) -> OperatorOutcome: ...

    def resume(self, *, dry_run: bool) -> OperatorOutcome: ...

    def stop(self, *, dry_run: bool) -> OperatorOutcome: ...


@dataclass(frozen=True)
class OperatorGroupInfo:
    """What the operator sees of one group and its agents."""

    name: str
    state: str
    """The registrant's lifecycle word, such as running or stopping."""

    stop: str | None
    """Once stopping, why: a fixed category, never free text."""

    paused: bool
    """Whether a pause of the whole group is in effect."""

    agents: list[OperatorAgentInfo]


class OperatorGroup(Protocol):
    """A named set of agents the operator can act on, and act on as a whole."""

    @property
    def agents(self) -> Mapping[str, OperatorAgent]: ...

    def info(self) -> OperatorGroupInfo: ...

    def pause(self, *, dry_run: bool) -> OperatorOutcome: ...

    def resume(self, *, dry_run: bool) -> OperatorOutcome: ...

    def stop(self, *, dry_run: bool) -> OperatorOutcome: ...


@contextmanager
def operator_group(name: str, group: OperatorGroup) -> Iterator[None]:
    """Make a group of agents addressable by the control channel for this block.

    Adds ``group`` to the active sample's operator groups under ``name`` and
    removes it on exit. Outside a sample it does nothing.

    Args:
        name: The group's name, unique in the sample.
        group: The group. Its agent names must not be used by another group
            in the sample.

    Raises:
        ValueError: The sample already has a group called ``name``, or an
            agent of one of the group's names in another group.
    """
    from inspect_ai.log._samples import sample_active

    sample = sample_active()
    if sample is None:
        yield
        return
    groups = sample.operator_groups
    if name in groups:
        raise ValueError(f"The sample already has an operator group named '{name}'.")
    for agent in group.agents:
        for other_name, other in groups.items():
            if agent in other.agents:
                raise ValueError(
                    f"Operator agent '{agent}' of group '{name}' is already in "
                    f"group '{other_name}' of the sample."
                )
    groups[name] = group
    try:
        yield
    finally:
        if groups.get(name) is group:
            del groups[name]


class OperatorResponse(NamedTuple):
    """An operator route's HTTP status and JSON body."""

    status: int
    content: dict[str, Any]


def _error(status: int, message: str) -> OperatorResponse:
    return OperatorResponse(status, {"error": message})


def _sample_not_found(sample_id: str, epoch: int) -> OperatorResponse:
    return _error(404, f"sample {sample_id} (epoch {epoch}) not found")


def _names(kind: str, names: list[str]) -> str:
    if not names:
        return "the sample has no addressable agents"
    return f"{kind}: {', '.join(names)}"


def sample_agents(eval_id: str, sample_id: str, epoch: int) -> OperatorResponse:
    """List a running sample's operator groups (``GET .../sample/agents``)."""
    from inspect_ai._control.state import find_active_sample

    sample = find_active_sample(eval_id, sample_id, epoch)
    if sample is None:
        return _sample_not_found(sample_id, epoch)
    return OperatorResponse(
        200,
        {
            "as_of": time.time(),
            "sample_id": sample.sample.id,
            "epoch": sample.epoch,
            "groups": [
                asdict(group.info()) for group in sample.operator_groups.values()
            ],
        },
    )


def sample_agent_action(
    eval_id: str,
    sample_id: str,
    epoch: int | None,
    action: str,
    *,
    agent: str | None,
    group: str | None,
    text: str | None,
    interrupt: bool | None,
    dry_run: bool,
) -> OperatorResponse:
    """Send one action to an agent or a group (``POST .../sample/agent/{action}``).

    Validates the request (400), finds the sample and the target (404, naming
    the targets there are), and calls the target's method. An outcome the
    target refuses is a 409 with its reason; otherwise the result carries the
    outcome's ``changed`` and ``detail``.

    ``text`` is the message's text, required for ``message`` and refused for
    the other actions. ``interrupt`` is accepted only with ``message``
    (``None`` when the request did not give it).
    """
    from inspect_ai._control.state import find_active_sample

    if epoch is None:
        return _error(
            400,
            "epoch is required — a defaulted epoch would silently target the "
            "epoch-1 attempt on a multi-epoch task",
        )
    if action not in OPERATOR_ACTIONS:
        return _error(
            400,
            f"action must be one of {', '.join(OPERATOR_ACTIONS)} (got '{action}')",
        )
    if (agent is None) == (group is None):
        return _error(400, "pass exactly one of agent and group")
    if action == "message":
        if agent is None:
            return _error(400, "message takes an agent, not a group")
        if text is None or not text.strip():
            return _error(400, "message needs a non-empty text in the request body")
    else:
        if interrupt is not None:
            return _error(400, "interrupt applies only to message")
        if text is not None:
            return _error(400, f"{action} takes no request body")

    sample = find_active_sample(eval_id, sample_id, epoch)
    if sample is None:
        return _sample_not_found(sample_id, epoch)
    groups = sample.operator_groups

    if group is not None:
        target_group = groups.get(group)
        if target_group is None:
            return _error(
                404,
                f"no group '{group}' in sample {sample_id} (epoch {epoch}); "
                f"{_names('groups', list(groups))}",
            )
        target: dict[str, str] = {"group": group}
        if action == "pause":
            outcome = target_group.pause(dry_run=dry_run)
        elif action == "resume":
            outcome = target_group.resume(dry_run=dry_run)
        else:
            outcome = target_group.stop(dry_run=dry_run)
    else:
        assert agent is not None
        matches = [
            (name, registered.agents[agent])
            for name, registered in groups.items()
            if agent in registered.agents
        ]
        if not matches:
            names = [
                name for registered in groups.values() for name in registered.agents
            ]
            return _error(
                404,
                f"no agent '{agent}' in sample {sample_id} (epoch {epoch}); "
                f"{_names('agents', names)}",
            )
        if len(matches) > 1:
            return _error(
                409,
                f"agent '{agent}' is in more than one group "
                f"({', '.join(name for name, _ in matches)})",
            )
        group_name, target_agent = matches[0]
        target = {"group": group_name, "agent": agent}
        if action == "message":
            assert text is not None
            outcome = target_agent.message(
                text, interrupt=bool(interrupt), dry_run=dry_run
            )
        elif action == "pause":
            outcome = target_agent.pause(dry_run=dry_run)
        elif action == "resume":
            outcome = target_agent.resume(dry_run=dry_run)
        else:
            outcome = target_agent.stop(dry_run=dry_run)

    if outcome.refused is not None:
        return OperatorResponse(409, {"error": outcome.refused, "target": target})
    return OperatorResponse(
        200,
        {
            "ok": True,
            "sample_id": sample.sample.id,
            "epoch": sample.epoch,
            "changed": outcome.changed,
            "dry_run": dry_run,
            "target": target,
            "detail": outcome.detail,
        },
    )
