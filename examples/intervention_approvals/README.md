# Intervention Mode with Approvals Demo

## Introduction

This example builds upon the intervention_mode example, adding more sophisticated approval mechanisms. We've implemented two types of approvals:

1. Tool-level approval: Specifically for bash commands, using a combination of an AllowListApprover and a HumanApprover.
2. Agent-level approval: Applied to all tool calls, using a HumanApprover.

This setup demonstrates how to integrate approval mechanisms into both tools and the agent loop itself.

## Key Components

### Approvers

We've implemented two types of approvers:

1. `AllowListApprover`: Automatically approves bash commands that are in a predefined list.
2. `HumanApprover`: Prompts the user to approve, reject, escalate, or terminate the execution of a tool call.

These approvers are managed by an `ApprovalManager` class, which can be configured with multiple approvers in a chain.

### Modified Bash Tool

The bash tool has been updated to integrate with the approval system:

```python:examples/intervention_approvals/intervention.py
@tool
def bash(timeout: int | None = None, user: str | None = None, approval_manager: Optional[ApprovalManager] = None) -> Tool:
    async def execute(cmd: str) -> str:
        if approval_manager:
            state = sample_state()
            if state is None:
                return "Error: No state found."
            tool_calls = get_tool_calls_from_state(state)
            if tool_calls is None:
                return "Error: No tool calls found in the current state."
            tool_call = next((tc for tc in tool_calls if tc.function == bash.name), None)
            if tool_call:
                approved, reason = approval_manager.get_approval(tool_call)
            else:
                return f"Error: No {bash.name} tool call found in the current state."
            if not approved:
                return f"Command rejected by the approval system. Reason: {reason}"
        # ... (rest of the bash tool implementation)
    return execute
```

### Modified Agent Loop

The agent loop has been updated to support agent-level approval:

```python:examples/intervention_approvals/intervention.py
@solver
def agent_loop(tools: list[Tool], approval_manager: Optional[ApprovalManager] = None) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        while True:
            output = await model.generate(state.messages, tools)
            state.output = output
            state.messages.append(output.message)
            if output.message.tool_calls:
                if approval_manager:
                    for tool_call in output.message.tool_calls:
                        approved, reason = approval_manager.get_approval(tool_call)
                        if not approved:
                            state.messages.append(ChatMessageTool(
                                tool_call_id=tool_call.id,
                                content=f"Command rejected by the approval system. Reason: {reason}"
                            ))
                            continue
                tool_output = await call_tools(output.message, tools)
                state.messages.extend(tool_output)
                print_tool_output(tool_output)
            else:
                # ... (rest of the agent loop implementation)
    return solve
```

## Usage

We've defined two tasks that demonstrate different approval setups:

1. `tool_call_intervention`: Uses an AllowListApprover and a HumanApprover for bash commands.
2. `agent_loop_intervention`: Uses a HumanApprover for all tool calls at the agent level.

You can run these tasks using the following code:

```python:examples/intervention_approvals/intervention.py
if __name__ == "__main__":
    from inspect_ai import eval
    tasks = [tool_call_intervention()]
    eval(tasks=tasks, model='openai/gpt-4o-mini', limit=1, log_buffer=1)
```

## Customization

You can customize this setup in several ways:

1. Modify the `AllowListApprover` to include more allowed commands or command-specific rules.
2. Create new types of approvers (e.g., a RegexApprover or an AIApprover).
3. Adjust the approval chain in the `ApprovalManager` to change the order or composition of approvers.
4. Apply approval mechanisms to other tools besides bash.

## Conclusion

This example demonstrates how to integrate sophisticated approval mechanisms into an Inspect agent. By using a combination of automatic and human approvers, you can create a flexible and secure system for controlling agent actions.