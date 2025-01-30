# Tasks


## Overview

This article documents both basic and advanced use of Inspect tasks,
which are the fundamental unit of integration for datasets, solvers, and
scorers. The following topics are explored:

- [Task Basics](#task-basics) describes the core components and options
  of tasks.

- [Parameters](#parameters) covers adding parameters to tasks to make
  them flexible and adaptable.

- [Solvers](#solvers) describes how to create tasks that can be used
  with many different solvers.

- [Task Reuse](#task-reuse) documents how to flexibly derive new tasks
  from existing task definitions.

- [Exploratory](#exploratory) provides guidance on doing exploratory
  task and solver development.

## Task Basics

Tasks provide a recipe for an evaluation consisting minimally of a
dataset, a solver, and a scorer (and possibly other options) and is
returned from a function decorated with `@task`. For example:

``` python
from inspect_ai import Task, task
from inspect_ai.dataset import json_datasets
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import chain_of_thought, generate

@task
def security_guide():
    return Task(
        dataset=json_dataset("security_guide.json"),
        solver=[chain_of_thought(), generate()],
        scorer=model_graded_fact()
    )
```

For convenience, tasks always define a default solver. That said, it is
often desirable to design tasks that can work with *any* solver so that
you can experiment with different strategies. The [Solvers](#solvers)
section below goes into depth on how to create tasks that can be
flexibly used with any solver.

### Task Options

While many tasks can be defined with only a dataset, solver, and scorer,
there are lots of other useful `Task` options. We won’t describe these
options in depth here, but rather provide a list along with links to
other sections of the documentation that cover their usage:

<table>
<colgroup>
<col style="width: 25%" />
<col style="width: 50%" />
<col style="width: 25%" />
</colgroup>
<thead>
<tr class="header">
<th>Option</th>
<th>Description</th>
<th>Docs</th>
</tr>
</thead>
<tbody>
<tr class="odd">
<td><code>epochs</code></td>
<td>Epochs to run for each dataset sample.</td>
<td><a href="scorers.qmd#reducing-epochs">Epochs</a></td>
</tr>
<tr class="even">
<td><code>config</code></td>
<td>Config for model generation.</td>
<td><a href="options.qmd#model-generation">Generate Config</a></td>
</tr>
<tr class="odd">
<td><code>setup</code></td>
<td>Setup solver(s) to run prior to the main solver.</td>
<td><a href="#setup-parameter">Sample Setup</a></td>
</tr>
<tr class="even">
<td><code>sandbox</code></td>
<td>Sandbox configuration for un-trusted code execution.</td>
<td><a href="sandboxing.qmd">Sandboxing</a></td>
</tr>
<tr class="odd">
<td><code>approval</code></td>
<td>Approval policy for tool calls.</td>
<td><a href="approval.qmd">Tool Approval</a></td>
</tr>
<tr class="even">
<td><code>metrics</code></td>
<td>Metrics to use in place of scorer metrics.</td>
<td><a href="scorers.qmd#scoring-metrics">Scoring Metrics</a></td>
</tr>
<tr class="odd">
<td><code>fail_on_error</code></td>
<td>Failure tolerance for samples.</td>
<td><a href="errors-and-limits.qmd#failure-threshold">Sample
Failure</a></td>
</tr>
<tr class="even">
<td><code>message_limit</code><br />
<code>token_limit</code><br />
<code>time_limit</code></td>
<td>Limits to apply to sample execution.</td>
<td><a href="errors-and-limits.qmd#sample-limits">Sample Limits</a></td>
</tr>
<tr class="odd">
<td><code>name</code><br />
<code>version</code><br />
<code>metadata</code></td>
<td>Eval log attributes for task.</td>
<td><a href="eval-logs.qmd">Eval Logs</a></td>
</tr>
</tbody>
</table>

You by and large don’t need to worry about these options until you want
to use the features they are linked to.

## Parameters

Task parameters make it easy to run variants of your task without
changing its source code. Task parameters are simply the arguments to
your `@task` decorated function. For example, here we provide parameters
(and default values) for system and grader prompts, as well as the
grader model:

<div class="code-with-filename">

**security.py**

``` python
from inspect_ai import Task, task
from inspect_ai.dataset import example_dataset
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import generate, system_message

@task
def security_guide(
    system="devops.txt", 
    grader="expert.txt",
    grader_model="openai/gpt-4o"
):
   return Task(
      dataset=example_dataset("security_guide"),
      solver=[system_message(system), generate()],
      scorer=model_graded_fact(
          template=grader, model=grader_model
      )
   )
```

</div>

Let’s say we had an alternate system prompt in a file named
`"researcher.txt"`. We could run the task with this prompt as follows:

``` bash
inspect eval security.py -T system="researcher.txt"
```

The `-T` CLI flag is used to specify parameter values. You can include
multiple `-T` flags. For example:

``` bash
inspect eval security.py \
   -T system="researcher.txt" -T grader="hacker.txt"
```

If you have several task paramaters you want to specify together, you
can put them in a YAML or JSON file and use the `--task-config` CLI
option. For example:

<div class="code-with-filename">

**config.yaml**

``` yaml
system: "researcher.txt"
grader: "hacker.txt"
```

</div>

Reference this file from the CLI with:

``` bash
inspect eval security.py --task-config=config.yaml
```

## Solvers

While tasks always include a *default* solver, you can also vary the
solver to explore other strategies and elicitation techniques. This
section covers best practices for creating solver-independent tasks.

### Solver Parameter

If you want to make your task work with a variety of solvers, the first
thing to do is add a `solver` parameter to your task function. For
example, let’s start with a CTF challenge task where the `solver` is
hard-coded:

``` python
from inspect_ai import Task, task
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash, python
from inspect_ai.scorer import includes

@task
def ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            use_tools([
                bash(timeout=180), 
                python(timeout=180)
            ]),
            generate()
        ],
        sandbox="docker",
        scorer=includes()
    )
```

This task uses the most naive solver possible (a simple tool use loop
with no additional elicitation). That might be okay for initial task
development, but we’ll likely want to try lots of different strategies.
We start by breaking the `solver` into its own function and adding an
alternative solver that uses the `basic_agent()`

``` python
from inspect_ai import Task, task
from inspect_ai.solver import basic_agent, chain, generate, use_tools
from inspect_ai.tool import bash, python
from inspect_ai.scorer import includes

@solver
def ctf_tool_loop():
    reutrn chain([
        use_tools([
            bash(timeout=180), 
            python(timeout=180)
        ]),
        generate()
    ])

@solver
def ctf_agent(max_attempts: int = 3):
    return basic_agent(
        tools=[
            bash(timeout=180), 
            python(timeout=180)
        ],
        max_attempts=max_attempts,
    ) 
 
@task
def ctf(solver: Solver | None = None):
    # use default tool loop solver if no solver specified
    if solver is None:
        solver = ctf_tool_loop()
   
    # return task
    return Task(
        dataset=read_dataset(),
        solver=solver,
        sandbox="docker",
        scorer=includes()
    )
```

Note that we use the `chain()` function to combine multiple solvers into
a composite one.

You can now switch between solvers when running the evaluation:

``` bash
# run with the default solver (ctf_tool_loop)
inspect eval ctf.py 

# run with the ctf agent solver
inspect eval ctf.py --solver=ctf_agent

# run with a different max_attempts
inspect eval ctf.py --solver=ctf_agent -S max_attempts=5
```

Note the use of the `-S` CLI option to pass an alternate value for
`max_attempts` to the `ctf_agent()` solver.

### Setup Parameter

In some cases, there will be important steps in the setup of a task that
*should not be substituted* when another solver is used with the task.
For example, you might have a step that does dynamic prompt engineering
based on values in the sample `metadata` or you might have a step that
initialises resources in a sample’s sandbox.

In these scenarios you can define a `setup` solver that is always run
even when another `solver` is substituted. For example, here we adapt
our initial example to include a `setup` step:

``` python
# prompt solver which should always be run
@solver
def ctf_prompt():
    async def solve(state, generate):
        # TODO: dynamic prompt engineering
        return state

@task
def ctf(solver: Solver | None = None):
    # use default tool loop solver if no solver specified
    if solver is None:
        solver = ctf_tool_loop()
   
    # return task
    return Task(
        dataset=read_dataset(),
        setup=ctf_prompt(),
        solver=solver,
        sandbox="docker",
        scorer=includes()
    )
```

## Task Reuse

The basic mechanism for task re-use is to create flexible and adaptable
base `@task` functions (which often have many parameters) and then
derive new higher-level tasks from them by creating additional `@task`
functions that call the base function.

In some cases though you might not have full control over the base
`@task` function (e.g. it’s published in a Python package you aren’t the
maintainer of) but you nevertheless want to flexibly create derivative
tasks from it. To do this, you can use the `task_with()` function, which
clones an existing task and enables you to override any of the task
fields that you need to.

For example, imagine you are dealing with a `Task` that hard-codes its
`sandbox` to a particular Dockerfile included with the task, and further
does not make a `solver` parameter available to swap in other solvers:

``` python
from inspect_ai import Task, task
from inspect_ai.solver import basic_agent
from inspect_ai.tool import bash
from inspect_ai.scorer import includes

@task
def hard_coded():
    return Task(
        dataset=read_dataset(),
        solver=basic_agent(tools=[bash()]),
        sandbox=("docker", "compose.yaml"),
        scorer=includes()
    )
```

Using `task_with()`, you can adapt this task to use a different `solver`
and `sandbox` entirely. For example, here we import the original
`hard_coded()` task from a hypothetical `ctf_tasks` package and provide
it with a different `solver` and `sandbox`, as well as give it a
`message_limit` (which we in turn also expose as a parameter of the
adapted task):

``` python
from inspect_ai import task, task_with
from inspect_ai.solver import solver

from ctf_tasks import hard_coded

@solver
def my_custom_agent():
    ## custom agent implementation
    ...

@task
def adapted(message_limit: int = 20):
    return task_with(
        hard_coded(),  # original task definition
        solver=my_custom_agent(),
        sandbox=("docker", "custom-compose.yaml"),
        message_limit=message_limit
    )
```

Tasks are recipes for an evaluation and represent the convergence of
many considerations (datasets, solvers, sandbox environments, limits,
and scoring). Task variations often lie at the intersection of these,
and the `task_with()` function is intended to help you produce exactly
the variation you need for a given evaluation.

## Exploratory

When developing tasks and solvers, you often want to explore how
changing prompts, generation options, solvers, and models affect
performance on a task. You can do this by creating multiple tasks with
varying parameters and passing them all to the `eval_set()` function.

Returning to the example from above, the `system` and `grader`
parameters point to files we are using as system message and grader
model templates. At the outset we might want to explore every possible
combination of these parameters, along with different models. We can use
the `itertools.product` function to do this:

``` python
from itertools import product

# 'grid' will be a permutation of all parameters
params = {
    "system": ["devops.txt", "researcher.txt"],
    "grader": ["hacker.txt", "expert.txt"],
    "grader_model": ["openai/gpt-4o", "google/gemini-1.5-pro"],
}
grid = list(product(*(params[name] for name in params)))

# run the evals and capture the logs
logs = eval_set(
    [
        security_guide(system, grader, grader_model)
        for system, grader, grader_model in grid
    ],
    model=["google/gemini-1.5-flash", "mistral/mistral-large-latest"],
    log_dir="security-tasks"
)

# analyze the logs...
plot_results(logs)
```

Note that we also pass a list of `model` to try out the task on multiple
models. This eval set will produce in total 16 tasks accounting for the
parameter and model variation.

See the article on [Eval Sets](eval-sets.qmd) to learn more about using
eval sets. See the article on [Eval Logs](eval-logs.qmd) for additional
details on working with evaluation logs.
