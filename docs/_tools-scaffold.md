1.  Redirect the model to another trajectory if its not on a productive course.
2.  Exercise more fine grained control over which, when, and how many tool calls are made, and how tool calling errors are handled.
3.  Have multiple `generate()` passes each with a distinct set of tools.

To do this, create a solver that emulates the default tool use loop and provides additional customisation as required. For example, here is a complete solver agent that has essentially the same implementation as the default `generate()` function:

``` python
@solver
def agent_loop(message_limit: int = 50):
    async def solve(state: TaskState, generate: Generate):

        # establish messages limit so we have a termination condition
        state.message_limit = message_limit

        # call the model in a loop
        while not state.completed:
            # call model
            output = await get_model().generate(state.messages, state.tools)

            # update state
            state.output = output
            state.messages.append(output.message)

            # make tool calls or terminate if there are none
            if output.message.tool_calls:
                state.messages.extend(call_tools(output.message, state.tools))
            else:
                break

        return state

    return solve
```

The `state.completed` flag is automatically set to `False` if `message_limit` or `token_limit` for the task is exceeded, so we check it at the top of the loop.

You can imagine several ways you might want to customise this loop:

1.  Adding another termination condition for the output satisfying some criteria.
2.  Urging the model to keep going after it decides to stop calling tools.
3.  Examining and possibly filtering the tool calls before invoking `call_tools()`
4.  Adding a critique / reflection step between tool calling and generate.
5. [Forking](agents-api.qmd#sec-forking) the `TaskState` and exploring several trajectories.

### Stop Reasons {#sec-stop-reasons}

One thing that a custom scaffold may do is try to recover from various conditions that cause the model to stop generating. You can find the reason that generation stopped in the `stop_reason` field of `ModelOutput`. For example:

``` python
output = await model.generate(state.messages, state.tools)
if output.stop_reason == "model_length":
    # do something to recover from context window overflow
```

Here are the possible values for `StopReason` :

| Stop Reason | Description |
|----|----|
| `stop` | The model hit a natural stop point or a provided stop sequence |
| `max_tokens` | The maximum number of tokens specified in the request was reached. |
| `model_length` | The model's context length was exceeded. |
| `tool_calls` | The model called a tool |
| `content_filter` | Content was omitted due to a content filter. |
| `unknown` | Unknown (e.g. unexpected runtime error) |

: {tbl-colwidths=\[35,65\]}

### Error Handling

By default expected errors (e.g. file not found, insufficient permission, timeouts, output limit exceeded etc.) are forwarded to the model for possible recovery. If you would like to intervene in the default error handling then rather than immediately appending the list of assistant messages returned from `call_tools()` to `state.messages` (as shown above), check the error property of these messages (which will be `None` in the case of no error) and proceed accordingly.