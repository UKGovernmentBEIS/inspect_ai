# Tasks


## Overview

This article documents both basic and advanced use of Inspect tasks,
which are the fundamental unit of integration for datasets, solvers, and
scorers. Topics covered include:

- [Task Basics](#task-basics) covers core task components and how to
  compose them.

- [Parameters](#parameters) demonstrates adding parameters to tasks to
  make them externally flexible and adaptable.

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
<td><a href="scorers.qmd#epoch-reduction">Epochs</a></td>
</tr>
<tr class="even">
<td><code>config</code></td>
<td>Config for model generation.</td>
<td><a href="models.qmd#generation-config">Generate Config</a></td>
</tr>
<tr class="odd">
<td><code>setup</code></td>
<td>Setup solver(s) to run prior to the main solver.</td>
<td><a href="#setup">Sample Setup</a></td>
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
solver to explore other strategies and elicitation techniques.

### Solver Roles

In the example above we combined together several solvers into a
composite solver. This illustrates the fact that there are two distinct
roles that solvers can play in the system:

1.  As a *composite* end-to-end specification of how to solve a task.

2.  As a *component* that is chained together with other solvers to
    create a composite solver;

Some solvers are capable of playing both roles. For example,
`generate()` is a complete end-to-end solver (albeit a simple one) but
is often also used as a *component* within other solvers.

### Solver Functions

The most convenient way to create a composite solver is to define a
`@solver` decorated function that returns a chain of other solvers. For
example, imagine we have written a `tree_of_thought` module that we want
to use to create an additional solver. We can re-write the task to have
multiple solver functions (where `critique` is used as the default):

<div class="code-with-filename">

**theory.py**

``` python
from inspect_ai import Task, task
from inspect_ai.dataset import example_dataset
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import (               
  solver, chain, prompt_template, generate, self_critique
)

DEFAULT_PROMPT="{prompt}"

from tree_of_thought import TREE_PROMPT, generate_tree

@solver 
def critique():
    return chain(
        prompt_template(DEFAULT_PROMPT), 
        generate(), 
        self_critique()
    )

@solver
def tree_of_thought():
    return chain(
        prompt_template(TREE_PROMPT), 
        generate_tree()
    )

@task
def theory_of_mind():
    return Task(  
        dataset=example_dataset("theory_of_mind"),
        solver=critique(),
        scorer=model_graded_fact()
    )
```

</div>

Note that we use the `chain()` function to combine mutliple solvers into
a composite one.

You can switch between solvers when running the evaluation:

``` bash
# run with the default solver (critique)
$ inspect eval theory.py --model=openai/gpt-4

# run with the tree of thought solver
$ inspect eval theory.py --solver=tree_of_thought --model=openai/gpt-4
```

Composite solvers by no means need to be implemented using chains. While
chains are frequently used in more straightforward knowledge and
reasoning evaluations, fully custom solver functions are often used for
multi-turn dialog and agent evaluations.

### 

## Task Reuse

``` python
task_with
```

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
