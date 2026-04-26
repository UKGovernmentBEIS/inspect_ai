"""End-to-end tests for deepagent() using mockllm deterministic outputs."""

from inspect_ai import Task, eval
from inspect_ai.agent import deepagent, subagent
from inspect_ai.dataset import Sample
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model import ChatMessageSystem, ModelOutput, get_model
from inspect_ai.scorer import includes


def _eval_deepagent(
    agent_kwargs: dict,
    outputs: list[ModelOutput],
    input: str = "Do the task",
    target: str = "n/a",
    message_limit: int = 20,
) -> dict:
    """Helper to run a deepagent eval and return results."""
    agent_kwargs.setdefault("submit", True)
    da = deepagent(**agent_kwargs)
    task = Task(
        dataset=[Sample(input=input, target=target)],
        solver=da,
        scorer=includes(),
        message_limit=message_limit,
    )
    model = get_model("mockllm/model", custom_outputs=outputs)
    log = eval(task, model=model)[0]
    return {
        "log": log,
        "status": log.status,
        "messages": log.samples[0].messages if log.samples else [],
        "events": log.samples[0].events if log.samples else [],
    }


def _submit(answer: str = "done") -> ModelOutput:
    """Helper to create a submit tool call."""
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="submit",
        tool_arguments={"answer": answer},
    )


class TestMultiStepDelegation:
    def test_research_then_general(self) -> None:
        """Model delegates to research, then general sequentially."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Find background information.",
                    },
                ),
                ModelOutput.from_content(
                    "mockllm/model", "Found relevant background info."
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "general",
                        "prompt": "Execute based on findings.",
                    },
                ),
                ModelOutput.from_content(
                    "mockllm/model", "Executed the task successfully."
                ),
                _submit(),
            ],
        )
        assert result["status"] == "success"


class TestMemoryIntegration:
    def test_memory_write_then_delegate(self) -> None:
        """Model writes to memory, then delegates to subagent."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                # 1. Model writes to memory
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="memory",
                    tool_arguments={
                        "command": "create",
                        "path": "/memories/notes.txt",
                        "file_text": "Important finding: X=42",
                    },
                ),
                # 2. Model delegates to research
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Check memory for context, then investigate further.",
                    },
                ),
                # 3. Research subagent responds
                ModelOutput.from_content(
                    "mockllm/model", "Found X=42 in memory, confirmed."
                ),
                # 4. Outer agent finishes
                _submit(),
            ],
        )
        assert result["status"] == "success"


class TestTodoWriteIntegration:
    def test_create_and_update_plan(self) -> None:
        """Model creates a plan with todo_write, then works through it."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                # 1. Model creates a plan
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Research the topic", "status": "in_progress"},
                            {"content": "Analyze findings", "status": "pending"},
                        ]
                    },
                ),
                # 2. Model delegates research
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Research the topic.",
                    },
                ),
                # 3. Research responds
                ModelOutput.from_content("mockllm/model", "Research complete."),
                # 4. Model updates plan
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Research the topic", "status": "completed"},
                            {"content": "Analyze findings", "status": "in_progress"},
                        ]
                    },
                ),
                # 5. Model submits
                _submit(),
            ],
        )
        assert result["status"] == "success"


class TestSubmitIntegration:
    def test_submit_answer(self) -> None:
        """Model does work then submits an answer."""
        result = _eval_deepagent(
            agent_kwargs={"submit": True},
            target="42",
            outputs=[
                # 1. Model delegates to research
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Find the answer.",
                    },
                ),
                # 2. Research responds
                ModelOutput.from_content("mockllm/model", "The answer is 42."),
                # 3. Model submits
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "42"},
                ),
            ],
        )
        assert result["status"] == "success"


class TestCustomSubagents:
    def test_user_defined_subagent(self) -> None:
        """User-defined subagent is dispatched correctly."""
        custom = subagent(
            name="analyzer",
            description="Analyzes data.",
            prompt="You are a data analyzer.",
        )
        result = _eval_deepagent(
            agent_kwargs={"subagents": [custom]},
            outputs=[
                # 1. Model delegates to custom subagent
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "analyzer",
                        "prompt": "Analyze this data.",
                    },
                ),
                # 2. Analyzer responds
                ModelOutput.from_content("mockllm/model", "Analysis complete."),
                # 3. Outer agent finishes
                _submit(),
            ],
        )
        assert result["status"] == "success"


class TestInstructionsInPrompt:
    def test_instructions_in_system_message(self) -> None:
        """Verify instructions= text appears in the system message."""
        da = deepagent(instructions="Always respond in French.")
        task = Task(
            dataset=[Sample(input="Test", target="n/a")],
            solver=da,
            scorer=includes(),
            message_limit=5,
        )
        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", "Bonjour."),
            ],
        )
        log = eval(task, model=model)[0]
        assert log.samples
        system_msgs = [
            m for m in log.samples[0].messages if isinstance(m, ChatMessageSystem)
        ]
        assert len(system_msgs) > 0
        assert "Always respond in French." in system_msgs[0].content


class TestMemoryKillSwitch:
    def test_memory_false_no_memory_tool(self) -> None:
        """memory=False means memory tool is not available."""
        result = _eval_deepagent(
            agent_kwargs={"memory": False},
            outputs=[
                # Model tries to use memory — should fail
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="memory",
                    tool_arguments={
                        "command": "view",
                        "path": "/memories",
                    },
                ),
                # Model recovers and finishes
                _submit(),
            ],
        )
        assert result["status"] == "success"
        # The memory tool call should have produced an error
        tool_events = [e for e in result["events"] if isinstance(e, ToolEvent)]
        memory_events = [e for e in tool_events if e.function == "memory"]
        if memory_events:
            assert memory_events[0].error is not None


class TestFullWorkflow:
    def test_memory_plan_delegate_submit(self) -> None:
        """Full lifecycle: memory → plan → delegate → submit."""
        result = _eval_deepagent(
            agent_kwargs={"submit": True},
            target="success",
            outputs=[
                # 1. Write context to memory
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="memory",
                    tool_arguments={
                        "command": "create",
                        "path": "/memories/context.txt",
                        "file_text": "Task requires finding X.",
                    },
                ),
                # 2. Create a plan
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Research X", "status": "in_progress"},
                            {"content": "Synthesize findings", "status": "pending"},
                        ]
                    },
                ),
                # 3. Delegate to research
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Research X.",
                    },
                ),
                # 4. Research subagent responds
                ModelOutput.from_content("mockllm/model", "X = success."),
                # 5. Update plan
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Research X", "status": "completed"},
                            {"content": "Synthesize findings", "status": "completed"},
                        ]
                    },
                ),
                # 6. Submit answer
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "success"},
                ),
            ],
        )
        assert result["status"] == "success"


class TestPlanSubagent:
    def test_plan_dispatch(self) -> None:
        """Delegate to the plan subagent specifically."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "plan",
                        "prompt": "Create a plan for solving this problem.",
                    },
                ),
                ModelOutput.from_content(
                    "mockllm/model", "Plan: Step 1, Step 2, Step 3."
                ),
                _submit(),
            ],
        )
        assert result["status"] == "success"
        tool_events = [e for e in result["events"] if isinstance(e, ToolEvent)]
        task_events = [e for e in tool_events if e.function == "task"]
        assert len(task_events) == 1
        assert task_events[0].error is None


class TestGeneralInheritsParentTools:
    def test_parent_tool_available_to_general(self) -> None:
        """A tool passed to deepagent(tools=[...]) is usable by general."""
        from inspect_ai.tool import think

        result = _eval_deepagent(
            agent_kwargs={"tools": [think()]},
            outputs=[
                # Delegate to general which should have think() available
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "general",
                        "prompt": "Think carefully then answer.",
                    },
                ),
                # General subagent uses think tool
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="think",
                    tool_arguments={"thought": "Let me consider..."},
                ),
                # General subagent finishes
                ModelOutput.from_content("mockllm/model", "Thought it through."),
                # Outer agent finishes
                _submit(),
            ],
        )
        assert result["status"] == "success"


class TestTodoWriteDisabled:
    def test_todo_write_false(self) -> None:
        """todo_write=False means todo_write tool is not available."""
        result = _eval_deepagent(
            agent_kwargs={"todo_write": False},
            outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Step 1", "status": "pending"},
                        ]
                    },
                ),
                _submit(),
            ],
        )
        assert result["status"] == "success"
        tool_events = [e for e in result["events"] if isinstance(e, ToolEvent)]
        tw_events = [e for e in tool_events if e.function == "todo_write"]
        if tw_events:
            assert tw_events[0].error is not None


class TestMultipleCallsToSameSubagent:
    def test_research_called_twice(self) -> None:
        """Model delegates to research twice in one session."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                # First research call
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Research topic A.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Found info about A."),
                # Second research call
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Research topic B.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Found info about B."),
                # Outer agent finishes
                _submit(),
            ],
        )
        assert result["status"] == "success"
        tool_events = [e for e in result["events"] if isinstance(e, ToolEvent)]
        task_events = [e for e in tool_events if e.function == "task"]
        assert len(task_events) == 2


class TestInterleavedToolUseAndDelegation:
    def test_mixed_tool_calls(self) -> None:
        """Model interleaves memory, delegation, and todo_write."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                # 1. Check memory
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="memory",
                    tool_arguments={"command": "view", "path": "/memories"},
                ),
                # 2. Delegate to research
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Find data.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Found data."),
                # 3. Save to memory
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="memory",
                    tool_arguments={
                        "command": "create",
                        "path": "/memories/data.txt",
                        "file_text": "Data found by research agent.",
                    },
                ),
                # 4. Update plan
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="todo_write",
                    tool_arguments={
                        "todos": [
                            {"content": "Find data", "status": "completed"},
                            {"content": "Process data", "status": "in_progress"},
                        ]
                    },
                ),
                # 5. Delegate to general
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "general",
                        "prompt": "Process the data.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Data processed."),
                # 6. Finish
                _submit(),
            ],
        )
        assert result["status"] == "success"
        tool_events = [e for e in result["events"] if isinstance(e, ToolEvent)]
        tool_names = [e.function for e in tool_events]
        assert "memory" in tool_names
        assert "task" in tool_names
        assert "todo_write" in tool_names


class TestCustomPromptPlaceholders:
    def test_custom_prompt_reaches_model(self) -> None:
        """Custom prompt= with placeholders is what the model sees."""
        da = deepagent(
            prompt="CUSTOM_START\n\n{core_behavior}\n\n{instructions}\n\nCUSTOM_END",
            instructions="Special rule: always verify.",
        )
        task = Task(
            dataset=[Sample(input="Test", target="n/a")],
            solver=da,
            scorer=includes(),
            message_limit=5,
        )
        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", "Done."),
            ],
        )
        log = eval(task, model=model)[0]
        assert log.samples
        system_msgs = [
            m for m in log.samples[0].messages if isinstance(m, ChatMessageSystem)
        ]
        assert len(system_msgs) > 0
        content = system_msgs[0].content
        assert "CUSTOM_START" in content
        assert "CUSTOM_END" in content
        assert "Special rule: always verify." in content
        assert "Complete tasks autonomously" in content


class TestUnknownToolCall:
    def test_unknown_tool_graceful_error(self) -> None:
        """Model calls a tool that doesn't exist — should get an error, not crash."""
        result = _eval_deepagent(
            agent_kwargs={},
            outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="nonexistent_tool",
                    tool_arguments={"arg": "value"},
                ),
                _submit(),
            ],
        )
        assert result["status"] == "success"
