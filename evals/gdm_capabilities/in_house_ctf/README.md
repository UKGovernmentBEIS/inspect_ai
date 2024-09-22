# GDM Dangerous Capabilities: In House CTF

This directory includes 13 Capture The Flag challenges from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)).

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation.

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. See the [Docker Images](#docker-images) section below for details on using locally built Docker images.

## Evaluation

Evaluate all 13 challenges against any model with:

``` bash
$ inspect eval task.py --model google/gemini-1.5-pro
```

You can also evaluate multiple models at once:

``` bash
$ inspect eval task.py --model openai/gpt-4o,google/gemini-1.5-pro
```

To evaluate a subset of challenges use the `challenges` task parameter

``` bash
$ inspect eval task.py -T challenges=db_3 --model google/gemini-1.5-pro
$ inspect eval task.py -T challenges=idor,spray --model openai/gpt-4o 
```

### Epochs

The GDM paper evaluated each challenge 10 times, reporting success if at least 1 challenge of the 10 was successful. The same default number of epochs (10) is used here, however you can modify this with the `--epochs` option:

``` bash
$ inspect eval task.py --epochs=5 --model openai/gpt-4o 
```

### Options

There are two other optional task parameters:

| Option | Description |
|----|----|
| `max_attempts` | The number of incorrect submissions to allow before ending the challenges (defaults to 1). |
| `max_messages` | The maximum number of messages allowed in the conversation before ending the challenges (defaults to 50). |

For example:

``` bash
$ inspect eval task.py --model openai/gpt-4o \
    -T max_attempts=2 -T max_messages=75
```

## Eval Sets

The best way to run groups of evaluation tasks is to use the `eval_set()` function (or `inspect eval-set` command), which provides automatic retries and recovery of samples from failed runs. For example, here we run each task against two models with an eval set:

``` python
from inspect_ai import eval_set

success, logs = eval_set(
  "task.py", 
  log_dir="logs-in-house-ctf",
  model=["openai/gpt-4o", "google/gemini-1.5-pro"]
)
```

Or equivalently:

``` bash
$ inspect eval-set task.py \
    --log-dir=logs-in-house-ctf \
    --model=openai/gpt-4o,google/gemini-1.5-pro \
```

Retries will occur automatically, and if the retry limit is exceeded you can re-run the eval set on the same log directory and it will pickup where it left off (note that each distinct run of eval set should have a dedicated log directory). See the article on [Eval Sets](https://inspect.ai-safety-institute.org.uk/eval-sets.html) to learn more.

## Log per Challenge

To run the entire suite as individual challenges (so that each challenge has its own log file), use `eval_set()` with a task dynamically created for each challenge:

``` python
from inspect_ai import eval_set
from task import in_house_ctf

challenges = [
  "cmd_injection", "db_3", "grafana", "idor", "privesc_7z", "privesc_bash",
  "privesc_find", "privesc_sed", "pw_reuse", "spray", "sqli", "ssh", "webmin"
]
tasks = [in_house_ctf(challenges=challenge) for challenge in challenges]

success, logs = eval_set(
  tasks,
  log_dir="logs-in-house-ctf-gemini",
  model="google/gemini-1.5-pro"
)
```

## Docker Images {#docker-images}

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. The Dockerfiles used to build these images have been provided as well (adapted from the original repository with minor modifications).

Note that the flag values in the Dockerfiles have been replaced with placeholders `REPLACE_ME_WITH_RANDOM_FLAG_N` to prevent them from ending up in web crawler accessible GitHub data. The actual values are baked into the remote Docker images and will be accessed during evaluation run. If you'd like to build images locally images, make sure to replace these placeholders with your actual flag values and update the `compose.yaml` files to use local docker images. For example, you would replace this:

``` yaml
services:
  idor:
    image: marshw/idor
```

With this:

``` yaml
services:
  default: 
    build: .
```

Again, remembering to replace the `REPLACE_ME_WITH_RANDOM_FLAG_N` within the Dockerfile.