from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ModelName, ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    Setting,
    TaskState,
    Workspace,
    basic_agent,
    setting,
    system_message,
)
from inspect_ai.solver._task_state import set_sample_state
from inspect_ai.tool import Tool, tool
from inspect_ai.util import store


@tool
def addition():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute


def test_setting_defaults():
    s = Setting()
    assert s.workspaces == ()
    assert s.tools == ()
    assert s.on_turn is None


def test_workspace_defaults():
    ws = Workspace()
    assert ws.name == "default"
    assert ws.description == ""
    assert ws.user is None


def test_workspace_with_all_fields():
    ws = Workspace(name="main", description="Primary workspace", user="hacker")
    assert ws.name == "main"
    assert ws.description == "Primary workspace"
    assert ws.user == "hacker"


def test_setting_with_workspaces():
    s = Setting(
        workspaces=(
            Workspace(name="default", description="Workspace", user="user"),
            Workspace(name="db", description="Database", user="postgres"),
        ),
    )
    assert len(s.workspaces) == 2
    assert s.workspaces[0].name == "default"
    assert s.workspaces[1].name == "db"


def test_setting_accessor_returns_none_when_no_state():
    assert setting() is None


def test_task_state_setting_property():
    s = Setting(workspaces=(Workspace(description="test"),))
    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=0,
        epoch=1,
        input="test",
        messages=[ChatMessageUser(content="test")],
        setting=s,
    )
    assert state.setting is s

    # setter works
    s2 = Setting()
    state.setting = s2
    assert state.setting is s2


def test_setting_accessor_returns_setting_from_state():
    s = Setting(tools=(addition(),))
    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=0,
        epoch=1,
        input="test",
        messages=[ChatMessageUser(content="test")],
        setting=s,
    )
    set_sample_state(state)
    result = setting()
    assert result is s
    assert len(result.tools) == 1


def test_task_with_static_setting():
    s = Setting(workspaces=(Workspace(description="test"),))
    task = Task(
        dataset=[Sample(input="test", target="test")],
        setting=s,
        scorer=includes(),
    )
    assert task.setting is s


def test_task_with_factory_setting():
    def make_setting(sample: Sample) -> Setting:
        return Setting(tools=(addition(),))

    task = Task(
        dataset=[Sample(input="test", target="test")],
        setting=make_setting,
        scorer=includes(),
    )
    assert callable(task.setting)


def test_setting_workspace_creates_bash_in_basic_agent():
    """Test that workspaces cause scaffolding to create bash tools."""
    s = Setting(
        workspaces=(
            Workspace(name="default", description="Workspace", user="testuser"),
        ),
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0"])],
        setting=s,
        solver=basic_agent(
            tools=[],
            message_limit=5,
        ),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            )
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    model_event = next(
        event for event in log.samples[0].transcript.events if event.event == "model"
    )
    tool_names = {t.name for t in model_event.tools}
    assert "bash" in tool_names
    assert "submit" in tool_names


def test_setting_tools_merged_into_basic_agent():
    """Test that Setting.tools are merged into basic_agent."""
    s = Setting(tools=(addition(),))
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0"])],
        setting=s,
        solver=basic_agent(
            init=system_message(
                "You are a helpful assistant. Call submit() when done."
            ),
            tools=[],
            message_limit=5,
        ),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            )
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    model_event = next(
        event for event in log.samples[0].transcript.events if event.event == "model"
    )
    tool_names = {t.name for t in model_event.tools}
    assert "addition" in tool_names
    assert "submit" in tool_names


def test_setting_tool_dedup():
    """Test that setting tools override solver tools with the same name."""

    @tool(name="addition")
    def custom_addition():
        async def execute(x: int, y: int):
            """Add numbers but returns wrong answer.

            Args:
                x (int): First number.
                y (int): Second number.
            """
            return x + y + 100

        return execute

    s = Setting(tools=(addition(),))
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0"])],
        setting=s,
        solver=basic_agent(
            tools=[custom_addition()],
            message_limit=5,
        ),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            )
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"


def test_setting_on_turn_stops():
    """Test that on_turn returning False stops the agent."""

    async def stop_after_two() -> bool | str | None:
        s = store()
        n = s.get("turn_count", 0) + 1
        s.set("turn_count", n)
        if n >= 2:
            return False
        return None

    s = Setting(on_turn=stop_after_two)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        setting=s,
        solver=basic_agent(
            tools=[addition()],
            message_limit=50,
        ),
        scorer=includes(),
    )

    model = get_model("mockllm/model")
    log = eval(task, model=model)[0]
    assert log.status == "success"
    model_events = sum(
        1 for event in log.samples[0].transcript.events if event.event == "model"
    )
    assert model_events == 2


def test_setting_on_turn_injects_message():
    """Test that on_turn returning a string injects a user message."""

    async def inject_then_stop() -> bool | str | None:
        s = store()
        n = s.get("turn_count", 0) + 1
        s.set("turn_count", n)
        if n == 1:
            return "Please try a different approach."
        return False

    s = Setting(on_turn=inject_then_stop)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        setting=s,
        solver=basic_agent(
            tools=[addition()],
            message_limit=50,
        ),
        scorer=includes(),
    )

    model = get_model("mockllm/model")
    log = eval(task, model=model)[0]
    assert log.status == "success"

    user_messages = [
        m.content for m in log.samples[0].messages if isinstance(m, ChatMessageUser)
    ]
    assert "Please try a different approach." in user_messages


def test_factory_setting_per_sample():
    """Test that callable setting creates per-sample settings."""

    def make_setting(sample: Sample) -> Setting:
        tools_list: tuple[Tool, ...] = ()
        if sample.metadata and sample.metadata.get("needs_addition"):
            tools_list = (addition(),)
        return Setting(tools=tools_list)

    task = Task(
        dataset=[
            Sample(
                id="with_tool",
                input="What is 1 + 1?",
                target="2",
                metadata={"needs_addition": True},
            ),
            Sample(
                id="without_tool",
                input="Say hello",
                target="hello",
                metadata={"needs_addition": False},
            ),
        ],
        setting=make_setting,
        solver=basic_agent(
            tools=[],
            message_limit=5,
        ),
        scorer=includes(),
    )

    submit_output = ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="submit",
        tool_arguments={"answer": "2"},
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[submit_output] * 2,
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    sample_with = next(s for s in log.samples if s.id == "with_tool")
    model_event = next(
        event for event in sample_with.transcript.events if event.event == "model"
    )
    tool_names = {t.name for t in model_event.tools}
    assert "addition" in tool_names

    sample_without = next(s for s in log.samples if s.id == "without_tool")
    model_event = next(
        event for event in sample_without.transcript.events if event.event == "model"
    )
    tool_names = {t.name for t in model_event.tools}
    assert "addition" not in tool_names


def test_setting_workspace_creates_bash_in_react():
    """Test that workspaces cause react scaffolding to create bash tools."""
    s = Setting(
        workspaces=(
            Workspace(name="default", description="Workspace", user="testuser"),
        ),
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0"])],
        setting=s,
        solver=react(tools=[]),
        scorer=includes(),
        message_limit=5,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            )
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    model_event = next(
        event for event in log.samples[0].transcript.events if event.event == "model"
    )
    tool_names = {t.name for t in model_event.tools}
    assert "bash" in tool_names
    assert "submit" in tool_names


def test_setting_on_turn_stops_in_react():
    """Test that on_turn returning False stops the react agent."""

    async def stop_after_two() -> bool | str | None:
        s = store()
        n = s.get("turn_count", 0) + 1
        s.set("turn_count", n)
        if n >= 2:
            return False
        return None

    s = Setting(on_turn=stop_after_two)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        setting=s,
        solver=react(tools=[addition()]),
        scorer=includes(),
        message_limit=50,
    )

    model = get_model("mockllm/model")
    log = eval(task, model=model)[0]
    assert log.status == "success"
    model_events = sum(
        1 for event in log.samples[0].transcript.events if event.event == "model"
    )
    assert model_events == 2


def test_setting_on_turn_injects_message_in_react():
    """Test that on_turn returning a string injects a user message in react."""

    async def inject_then_stop() -> bool | str | None:
        s = store()
        n = s.get("turn_count", 0) + 1
        s.set("turn_count", n)
        if n == 1:
            return "Please try a different approach."
        return False

    s = Setting(on_turn=inject_then_stop)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        setting=s,
        solver=react(tools=[addition()]),
        scorer=includes(),
        message_limit=50,
    )

    model = get_model("mockllm/model")
    log = eval(task, model=model)[0]
    assert log.status == "success"

    user_messages = [
        m.content for m in log.samples[0].messages if isinstance(m, ChatMessageUser)
    ]
    assert "Please try a different approach." in user_messages
