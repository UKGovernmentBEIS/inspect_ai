



from inspect_ai.model import call_tools
from inspect_ai.model._model import get_model
from inspect_ai.solver import Plan
from inspect_ai.solver import Generate, Solver, TaskState
from inspect_ai.solver._prompt import system_message
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool import tool, Tool, ToolResult
from inspect_ai.util import store

DEFAULT_REACT_SYSTEM_PROMPT="""
Each message may perform one function call. You will
see the result of the function right after sending 
the message. If you need to perform multiple actions,
you can always send more messages with subsequent 
function calls. Do some reasoning before your actions,
describing what function calls you are going to use 
and how they fit into your plan. 

When you have completed the task and have a result, 
call the submit() tool to communicate it.
"""

def react_agent(
    preamble: str | Solver = DEFAULT_REACT_SYSTEM_PROMPT,
    tools: list[Tool] = [],
    max_attempts: int = 1,
    incorrect_message: str = "Hey, that was incorrect!",
    continue_message = "Hey, keep going, you can do it!"
) -> Plan:


    @tool
    def submit() -> Tool:
        async def execute(answer: str) -> ToolResult:

            # TODO: implement max_attempts
            store().set("answer", answer)
            return "good job"
        
        return execute



    def agent_loop() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model()
            while True:
                # generate output and append assistant message
                state.output = await model.generate(state.messages, state.tools)
                state.messages.append(state.output.message)

                # resolve tools calls (if any)
                if state.output.message.tool_calls:
                    state.messages.extend(
                        await call_tools(state.output.message, state.tools)
                    )

                    # TODO: check whether we've accepted an answer

                # no tool calls: model gave up without submitting
                else:
                    # TODO: do we need some max_attempts logic here?
                    break

            return state

        return solve
    

    return Plan([
        system_message(preamble) if isinstance(preamble, str) else preamble,
        use_tools(tools + [submit()]),
        agent_loop()
    ])

