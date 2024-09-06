from inspect_ai.model import call_tools, ChatMessageUser, get_model

from inspect_ai.solver import Generate, Plan, Solver, TaskState, system_message, use_tools
from inspect_ai.tool import tool, Tool, ToolResult, ToolCall, tool_with
from inspect_ai.util import store

DEFAULT_SYSTEM_PROMPT="""
Each message may perform one function call. You will see the result of the function
right after sending the message. If you need to perform multiple actions, you can 
always send more messages with subsequent function calls. Do some reasoning before 
your actions, describing what function calls you are going to use and how they fit
into your plan. 

When you have completed the task and have a result, call the {submit}() tool to 
communicate it.
"""


DEFAULT_INCORRECT_MESSAGE = """
Your submission was incorrect. Please proceed and attempt to find the correct answer."
"""

DEFAULT_CONTINUE_MESSAGE = "Please proceed to the next step using your best judgement."

DEFAULT_SUBMIT_TOOL_NAME = "submit"
DEFAULT_SUBMIT_TOOL_DESCRITION = "Submit an answer for evaluation."
DEFAULT_SUBMIT_TOOL_RESPONSE = "Your submission will be evaluated for correctness."

def basic_agent(
    tools: list[Tool] = [],
    *,
    max_attempts: int = 1,
    preamble: str | Solver = DEFAULT_SYSTEM_PROMPT,
    incorrect_message: str = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_tool_name: str = DEFAULT_SUBMIT_TOOL_NAME,
    submit_tool_description: str = DEFAULT_SUBMIT_TOOL_DESCRITION,
    submit_tool_response: str = DEFAULT_SUBMIT_TOOL_RESPONSE
) -> Plan:

    # state shared between submit tool and agent_loop
    ANSWER = "basic_agent:answer"

    # resolve preamble solver
    if isinstance(preamble, str):
        preamble = system_message(preamble.format(submit=submit_tool_name))

    # submission tool
    @tool
    def submit() -> Tool:

        async def execute(answer: str) -> ToolResult:
            """Submit an answer for evaluation.
            
            Args:
              answer (str): Submitted answer 
            """
            # set the answer (it will evaluated by the main loop)
            store().set(ANSWER, answer)

            # thank the model for its submission!
            return submit_tool_response
        
        return execute
    
    # enable customisation of submit tool name/description
    submit_tool = [tool_with(submit(), submit_tool_name, submit_tool_description)]

    # helper to check if a submission was attempted
    def answer_submitted(tool_calls: list[ToolCall]) -> bool:
        return any([tool for tool in tool_calls if tool.function == "submit"])

    # main agent loop
    def agent_loop() -> Solver:

        # get a reference to the evaluated model
        model = get_model()

        async def solve(state: TaskState, generate: Generate) -> TaskState:
                     
            # track attempts
            attempts = 0

            # main loop
            while True:

                # check for completed (if we hit a limit e.g. max_messages)
                if state.completed:
                    break

                # generate output and append assistant message
                state.output = await model.generate(state.messages, state.tools)
                state.messages.append(state.output.message)

                # resolve tools calls (if any)
                if state.output.message.tool_calls:
                    # call tool functions
                    state.messages.extend(
                        await call_tools(state.output.message, state.tools)
                    )

                    # was an answer submitted?
                    if answer_submitted(state.output.message.tool_calls):
                        # get the answer and score it (exit if correct)
                        answer = store().get(ANSWER)
                        state.output.completion = answer
                        if score(state):
                            break
                            
                        # check attempts
                        attempts += 1
                        if attempts >= max_attempts:
                            break

                        # notify the model that it was incorrect
                        state.messages.append(ChatMessageUser(content=incorrect_message))

                # no tool calls: model gave up without submitting
                else:
                    # check attempts
                    attempts += 1
                    if attempts >= max_attempts:
                        break

                    # urge the model to continue 
                    state.messages.append(ChatMessageUser(content=continue_message))
                    
            return state

        return solve
    
    # return plan
    return Plan([
        preamble,
        use_tools(tools + [submit_tool]),
        agent_loop()
    ])



# imagine we have a function that can call the scorer
def score(state: TaskState) -> bool:
    return True
