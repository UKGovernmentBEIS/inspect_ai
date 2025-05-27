

To run an agent with one or more limits, pass the limit object in the `limits` argument to a function like `handoff()`, `as_tool()`, `as_solver()` or `run()` (see [Using Agents](agents.qmd#using-agents) for details on the various ways to run agents).

Here we limit an agent we are including as a solver to 500K tokens:

``` python
eval(
    task="research_bench", 
    solver=as_solver(web_surfer(), limits=[token_limit(1024*500)])
)
```

Here we limit an agent `handoff()` to 500K tokens:

``` python
eval(
    task="research_bench", 
    solver=[
        use_tools(
            addition(),
            handoff(web_surfer(), limits=[token_limit(1024*500)]),
        ),
        generate()
    ]
)
```

### Limit Exceeded

Note that when limits are exceeded during an agent's execution, the way this is handled differs depending on how the agent was executed:

-   For agents used via `as_solver()`, if a limit is exceeded then the sample will terminate (this is exactly how sample-level limits work).


-   For agents that are `run()` directly with limits, their limit exceptions will be caught and returned in a tuple. Limits other than the ones passed to `run()` will propagate up the stack.

    ``` python
    from inspect_ai.agent import run

    state, limit_error = await run(
        agent=web_surfer(), 
        input="What were the 3 most popular movies of 2020?",
        limits=[token_limit(1024*500)])
    )
    if limit_error:
        ...
    ```


-   For tool based agents (`handoff()` and `as_tool()`), if a limit is exceeded then a message to that effect is returned to the model but the *sample continues running*.
