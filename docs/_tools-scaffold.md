

1.  Redirect the model to another trajectory if its not on a productive course.
2.  Exercise more fine grained control over which, when, and how many tool calls are made, and how tool calling errors are handled.
4.  Have multiple `generate()` passes each with a distinct set of tools.


To do this, create a solver that emulates the default tool use loop and provides additional customisation as required. Here is the code at the core of Inspect tool use in `generate()`:

``` python
# call model
model = get_model()
output = await model.generate(state.messages, state.tools)

# update state with output
state.output = output
state.messages.append(output.message)

# call tools and update state
state.messages.extend(call_tools(output.message, state.tools))
```

This does everything that default `generate()` does, save for an outer loop to continue calling the mode as long as it continues calling tools. You could implement the outer loop as follows:

``` python
model = get_model()
while True:
    # call model
    output = await model.generate(state.messages, state.tools)

    # update state
    state.output = output
    state.messages.append(output.message)

    # make tool calls or terminate if there are none
    if output.message.tool_calls:
        state.messages.extend(call_tools(output.message, state.tools))
    else:
        break
```

You can imagine several ways you might want to customise this loop:

1.  Adding another termination condition for the output satisfying some criteria.
2.  Urging the model to keep going after it decides to stop calling tools.
3.  Examining and possibly filtering the tool calls before invoking `call_tools()`
4.  Adding a critique / reflection step between tool calling and generate.
5.  Deep copying the `TaskState` and exploring several trajectories.

Note that by default expected errors (e.g. file not found, insufficient, permission , timeouts, etc.) are forwarded to the model for possible recovery. If you would like to intervene in the default error handling then rather than immediately appending the list of assistant messages returned from `call_tools()` to `state.messages` (as shown above), check the error property of these messages (which will be `None` in the case of no error) and proceed accordingly.



