# GDM Dangerous Capabilities: In House CTF

This directory includes 13 Capture The Flag challenges migrated from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)).

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation.

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. The Dockerfiles used to build these images have been provided as well, they are adapted from the original repository with minor modifications.

Note that the flag values in the Dockerfiles have been replaced with placeholders `REPLACE_ME_WITH_RANDOM_FLAG_N` to prevent them from ending up in web crawler accessible GitHub data, the actual values are baked into the remote Docker images and will be accessed during evaluation run. If you'd like to build your local images, make sure to replace these placeholders with your actual flag values and update the `compose.yaml` files accordingly.

## Evaluation

To evaluate all of the challenges against various models (a separate Inspect task and log file will be created for each challenge):

``` bash
$ inspect eval task.py --model openai/gpt-4o
$ inspect eval task.py --model anthropic/claude-3-opus-20240229
$ inspect eval task.py --model google/gemini-1.5-pro
$ inspect eval task.py --model mistral/mistral-large-latest
```

To evaluate individual challenges:

``` bash
$ inspect eval task.py -T challenges=idor --model google/gemini-1.5-pro
$ inspect eval task.py -T challenges=db_3 --model google/gemini-1.5-pro
```

### Plans

The default plan uses the system prompt from the original paper (modified to emphsaise tool use) along with a bash tool customised to run under either the `root` or `app` user depending on the challenge. If you develop an alternate plan you can evaluate it with:

``` bash
$ inspect eval task.py --model openai/gpt-4o --plan plans.py@my_plan
```

The `task.py` module exports several functions which will be useful in the development of custom plans:

| Function | Description |
|------------------------------------|------------------------------------|
| `default_plan()` | Create an instance of the default plan parameterised by init (e.g. system message) and maximum attempts. |
| `default_system_message()` | System message used in the default plan. |
| `agent_bash_tool()` | Solver that dynamically provides a bash tool that runs under the appropriate user (`root` or `app`) depending on the challenge. |

### Options

There are two other optional task parameters:

-   `max_attempts` defines the number of incorrect submissions to allow before ending the challenges (defaults to 1).
-   `max_messages` defines the maximum number of messages allowed in the conversation before ending the challenges (defaults to 50).

For example:

``` bash
$ inspect eval task.py --model openai/gpt-4o -T max_attempts=2 -T max_messages=75
```

Further, the original GDM paper evaluated each challenge 10 times, scoring a success if at least one was successful. In this implementation the default is 1 epoch, however you can change this with `--epochs`:

``` bash
$ insepct eval task.py --model google/gemini-1.5-pro --epochs 10
```

## Eval Sets

The best way to run groups of evaluation tasks is to use the `eval_set()` function (or `inspect eval-set` command), which provides automatic retries and recovery of samples from failed runs. For example, to run the entire challenge suite for 5 epochs against three models:

``` python
from inspect_ai import eval_set

success, logs = eval_set(
  "task.py", 
  log_dir="logs-in-house-ctf",
  model=["openai/gpt-4o", "google/gemini-1.5-pro"],
  epochs=10
)
```

Or equivalently:

``` bash
$ inspect eval-set task.py \
    --log-dir=logs-in-house-ctf \
    --model=openai/gpt-4o,google/gemini-1.5-pro \
    --epochs=10
```

Retries will occur automatically, and if the retry limit is exceeded you can re-run the eval set on the same log directory and it will pickup where it left off (note that each distinct run of eval set should have a dedicated log directory). See the article on [Eval Sets](eval-sets.qmd) to learn more.

## Single Challenges

To run the entire suite as individual challenges (so that each challenge has its own log file), use `eval_set()` with a task dynamically created for each challenge:

``` python
from inspect_ai import eval_set
from task import in_house_ctf

challenges = [
  "cmd_injection",
  "db_3",
  "grafana",
  "idor",
  "privesc_7z",
  "privesc_bash",
  "privesc_find",
  "privesc_sed",
  "pw_reuse",
  "spray",
  "sqli",
  "ssh",
  "webmin"
]
tasks = [in_house_ctf(challenges=challenge) for challenge in challenges]

success, logs = eval_set(
  tasks,
  log_dir="logs-in-house-ctf",
  model=["anthropic/claude-3-opus-20240229", "google/gemini-1.5-pro"],
  epochs=5
)
```