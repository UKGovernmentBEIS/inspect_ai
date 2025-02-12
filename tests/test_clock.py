import asyncio
import pytest
from inspect_ai.solver._human_agent.commands.clock import StartCommand, StopCommand
from inspect_ai._util.format import format_progress_time
from inspect_ai.solver._human_agent.commands.clock import clock_action_event
from inspect_ai.solver._human_agent.commands.clock import StartCommand
from inspect_ai.solver._human_agent.commands.clock import StopCommand

# No additional imports required since all used modules are already imported.
@pytest.mark.asyncio
async def test_start_command_already_running_no_clock_event(monkeypatch):
    """
    Test that StartCommand.service does not log a "start" event when the clock is already running.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.running = True
    state.time = 100
    state.scorings = []  # required for render_status
    
    start_command = StartCommand()
    service_func = start_command.service(state)
    result = await service_func()
    
    assert state.running is True
    assert dummy_logger.info_calls == []
    assert isinstance(result, str)
@pytest.mark.asyncio
async def test_start_command_when_not_running_logs_clock_event(monkeypatch):
    """
    Test that StartCommand.service logs the 'start' event and updates the state when the clock is not running.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.running = False
    state.time = 150
    state.scorings = []
    
    start_command = StartCommand()
    service_func = start_command.service(state)
    result = await service_func()
    
    assert state.running is True
    expected_total_time = format_progress_time(state.time, False)
    assert len(dummy_logger.info_calls) == 1
    logged_data, logged_source = dummy_logger.info_calls[0]
    assert logged_data.get("action") == "start"
    assert logged_data.get("total_time") == expected_total_time
    assert logged_source == "human_agent"
    assert isinstance(result, str)
@pytest.mark.asyncio
async def test_stop_command_when_running_logs_clock_event(monkeypatch):
    """
    Test that StopCommand.service logs the 'stop' event and updates the state when the clock is running.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.running = True
    state.time = 200
    state.scorings = []
    
    stop_command = StopCommand()
    service_func = stop_command.service(state)
    result = await service_func()
    
    assert state.running is False
    expected_total_time = format_progress_time(state.time, False)
    assert len(dummy_logger.info_calls) == 1
    logged_data, logged_source = dummy_logger.info_calls[0]
    assert logged_data.get("action") == "stop"
    assert logged_data.get("total_time") == expected_total_time
    assert logged_source == "human_agent"
    assert isinstance(result, str)
@pytest.mark.asyncio
async def test_stop_command_when_not_running_no_clock_event(monkeypatch):
    """
    Test that StopCommand.service does not log a "stop" event when the clock is already stopped.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.running = False
    state.time = 250
    state.scorings = []
    
    stop_command = StopCommand()
    service_func = stop_command.service(state)
    result = await service_func()
    
    assert state.running is False
    assert dummy_logger.info_calls == []
    assert isinstance(result, str)
def test_start_command_cli_prints_expected(monkeypatch, capsys):
    """
    Test that StartCommand.cli prints the expected output.
    """
    monkeypatch.setattr(
        "inspect_ai.solver._human_agent.commands.clock.call_human_agent",
        lambda cmd: f"CLI response for {cmd}"
    )
    cmd = StartCommand()
    cmd.cli(None)
    captured = capsys.readouterr()
    assert "CLI response for start" in captured.out
@pytest.mark.cli
def test_stop_command_cli_prints_expected(monkeypatch, capsys):
    """
    Test that StopCommand.cli prints the expected output.
    """
    monkeypatch.setattr(
        "inspect_ai.solver._human_agent.commands.clock.call_human_agent",
        lambda cmd: f"CLI response for {cmd}"
    )
    cmd = StopCommand()
    cmd.cli(None)
    captured = capsys.readouterr()
    assert "CLI response for stop" in captured.out
@pytest.mark.asyncio
async def test_clock_action_event_logs_properly(monkeypatch):
    """
    Test that the clock_action_event function logs the expected event given the action and state.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.time = 300  # arbitrary time value
    
    clock_action_event("test", state)
    
    assert len(dummy_logger.info_calls) == 1
    logged_data, logged_source = dummy_logger.info_calls[0]
    expected_total_time = format_progress_time(state.time, False)
    
    assert logged_data.get("action") == "test"
    assert logged_data.get("total_time") == expected_total_time
    assert logged_source == "human_agent"
@pytest.mark.asyncio
async def test_sequential_start_and_stop_commands(monkeypatch):
    """
    Test that invoking StartCommand followed by StopCommand logs both 'start' and 'stop' events
    in sequence and updates the state accordingly.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    
    class DummyState:
        pass
    state = DummyState()
    state.running = False
    state.time = 50  # arbitrary time value
    state.scorings = []  # required for render_status
    
    start_command = StartCommand()
    start_service = start_command.service(state)
    result_start = await start_service()
    
    assert state.running is True
    expected_total_time = format_progress_time(state.time, False)
    assert len(dummy_logger.info_calls) == 1
    log_data_start, log_source_start = dummy_logger.info_calls[0]
    assert log_data_start.get("action") == "start"
    assert log_data_start.get("total_time") == expected_total_time
    assert log_source_start == "human_agent"
    assert isinstance(result_start, str)
    
    stop_command = StopCommand()
    stop_service = stop_command.service(state)
    result_stop = await stop_service()
    
    assert state.running is False
    assert len(dummy_logger.info_calls) == 2
    log_data_stop, log_source_stop = dummy_logger.info_calls[1]
    assert log_data_stop.get("action") == "stop"
    expected_total_time = format_progress_time(state.time, False)
    assert log_data_stop.get("total_time") == expected_total_time
    assert log_source_stop == "human_agent"
    assert isinstance(result_stop, str)
@pytest.mark.asyncio
async def test_start_command_incomplete_state_raises_error(monkeypatch):
    """
    Test that StartCommand.service raises an AttributeError when the state is missing the required 'time' attribute.
    This ensures that the code properly fails when passed an incomplete state object.
    """
    class DummyState:
        pass
    state = DummyState()
    state.running = False
    state.scorings = []  # required for render_status
    start_command = StartCommand()
    service_func = start_command.service(state)
    with pytest.raises(AttributeError):
        await service_func()
def test_command_properties():
    """
    Test that StartCommand and StopCommand have the expected properties (name, description, and group).
    """
    start_cmd = StartCommand()
    stop_cmd = StopCommand()
    assert start_cmd.name == "start"
    assert start_cmd.description == "Start the task clock (resume working)."
    assert start_cmd.group == 2
    assert stop_cmd.name == "stop"
    assert stop_cmd.description == "Stop the task clock (pause working)."
    assert stop_cmd.group == 2
@pytest.mark.asyncio
async def test_stop_command_incomplete_state_raises_error(monkeypatch):
    """
    Test that StopCommand.service raises an AttributeError when the state's missing the required 'time' attribute.
    This ensures that the function properly fails when passed an incomplete state object.
    """
    class DummyState:
        pass
    state = DummyState()
    state.running = True  # Ensure that the branch calling clock_action_event is executed
    state.scorings = []   # required for render_status
    stop_command = StopCommand()
    service_func = stop_command.service(state)
    
    with pytest.raises(AttributeError):
        await service_func()
@pytest.mark.asyncio
async def test_commands_missing_running_attribute():
    """
    Test that both StartCommand and StopCommand raise an AttributeError when the state is missing the 'running' attribute.
    This simulates an incomplete state setup where the required 'running' property is not provided.
    """
    class DummyState:
        pass
    state = DummyState()
    state.time = 120  # valid time for formatting
    state.scorings = []  # required for render_status
    start_command = StartCommand()
    with pytest.raises(AttributeError):
        service_func = start_command.service(state)
        await service_func()
    stop_command = StopCommand()
    with pytest.raises(AttributeError):
        service_func = stop_command.service(state)
        await service_func()
@pytest.mark.asyncio
async def test_start_service_returns_expected_render_status(monkeypatch):
    """
    Test that StartCommand.service returns the dummy output from a patched render_status
    and properly updates the state.running attribute.
    """
    dummy_status = "dummy status output"
    # Patch render_status from the clock module
    monkeypatch.setattr("inspect_ai.solver._human_agent.commands.clock.render_status", lambda state: dummy_status)
    
    # Create a dummy state object with the necessary attributes
    class DummyState:
        pass
    state = DummyState()
    state.running = False
    state.time = 123
    state.scorings = []
    
    start_command = StartCommand()
    service_func = start_command.service(state)
    
    result = await service_func()
    
    # Check that the service returns the patched dummy status and that the state is updated
    assert result == dummy_status
    assert state.running is True
def test_clock_action_event_missing_time_raises_error(monkeypatch):
    """
    Test that clock_action_event raises an AttributeError when the state is missing the required 'time' attribute.
    """
    class DummyLogger:
        def __init__(self):
            self.info_calls = []
        def info(self, data, source):
            self.info_calls.append((data, source))
    dummy_logger = DummyLogger()
    monkeypatch.setattr("inspect_ai.log._transcript.transcript", lambda: dummy_logger)
    class DummyState:
        pass
    state = DummyState()
    # Intentionally do not set state.time to simulate a missing 'time' attribute.
    with pytest.raises(AttributeError):
        clock_action_event("test_missing_time", state)