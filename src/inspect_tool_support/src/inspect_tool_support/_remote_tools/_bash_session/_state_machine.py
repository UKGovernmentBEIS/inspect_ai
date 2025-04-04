import asyncio
import time
from dataclasses import dataclass
from typing import Literal, TypeGuard

from inspect_tool_support._remote_tools._bash_session._timeout_params import (
    InteractiveParams,
    NonInteractiveParams,
    TimeoutParams,
)


@dataclass
class Idle:
    type: Literal["Idle"] = "Idle"


@dataclass
class SendingCommandOrInput:
    marker: str
    timeout_params: TimeoutParams
    type: Literal["SendingCommandOrInput"] = "SendingCommandOrInput"


@dataclass
class WaitingForComplete:
    marker: str
    completed_event: asyncio.Event
    timeout: float
    stdout_data: bytearray
    stderr_data: bytearray
    data_event: None = None
    type: Literal["WaitingForComplete"] = "WaitingForComplete"


@dataclass
class ProcessingCompletion:
    marker: str
    type: Literal["ProcessingCompletion"] = "ProcessingCompletion"


@dataclass
class WaitingForData:
    marker: str
    completed_event: asyncio.Event
    data_event: asyncio.Event
    debounce_complete_time: float
    timeout: float
    stdout_data: bytearray
    stderr_data: bytearray
    type: Literal["WaitingForData"] = "WaitingForData"


@dataclass
class WaitingForDebounce:
    marker: str
    completed_event: asyncio.Event
    debounce_complete_time: float
    timeout: float
    stdout_data: bytearray
    stderr_data: bytearray
    data_event: None = None
    type: Literal["WaitingForDebounce"] = "WaitingForDebounce"


@dataclass
class WaitingForModelToRequestMore:
    marker: str
    completed_event: asyncio.Event
    stdout_data: bytearray
    stderr_data: bytearray
    data_event: None = None
    type: Literal["WaitingForModelToRequestMore"] = "WaitingForModelToRequestMore"


State = (
    Idle
    | SendingCommandOrInput
    | WaitingForComplete
    | ProcessingCompletion
    | WaitingForData
    | WaitingForDebounce
    | WaitingForModelToRequestMore
)


def reducer(
    current_state: State,
) -> WaitingForComplete | WaitingForData | WaitingForDebounce:
    match current_state:
        case SendingCommandOrInput(
            marker=marker,
            timeout_params=NonInteractiveParams(timeout=timeout),
        ):
            return WaitingForComplete(
                marker=marker,
                completed_event=asyncio.Event(),
                stdout_data=bytearray(),
                stderr_data=bytearray(),
                timeout=timeout,
            )
        case SendingCommandOrInput(
            marker=marker,
            timeout_params=InteractiveParams(
                first_data_timeout=first_data_timeout, debounce=debounce
            ),
        ):
            return WaitingForData(
                marker=marker,
                completed_event=asyncio.Event(),
                data_event=asyncio.Event(),
                stdout_data=bytearray(),
                stderr_data=bytearray(),
                debounce_complete_time=time.time() + debounce,
                timeout=first_data_timeout,
            )
        case WaitingForData() as old_state:
            return WaitingForDebounce(
                marker=old_state.marker,
                completed_event=old_state.completed_event,
                stdout_data=old_state.stdout_data,
                stderr_data=old_state.stderr_data,
                debounce_complete_time=old_state.debounce_complete_time,
                timeout=old_state.debounce_complete_time - time.time(),
            )
        case state:
            assert False, f"Unexpected state: {state}"


def is_state_expecting_data(
    state: State,
) -> TypeGuard[
    WaitingForComplete
    | WaitingForData
    | WaitingForDebounce
    | WaitingForModelToRequestMore
]:
    return (
        state.type == "WaitingForComplete"
        or state.type == "WaitingForData"
        or state.type == "WaitingForDebounce"
        or state.type == "WaitingForModelToRequestMore"
    )
