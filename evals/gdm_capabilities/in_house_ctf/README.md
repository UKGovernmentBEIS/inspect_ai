# GDM Dangerous Capabilities: In House CTF

This directory includes 13 Capture The Flag challenges from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)).

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation.

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. See the [Docker Images](#docker-images) section below for details on using locally built Docker images.

## Evaluation

Evaluate all 13 challenges against any model with:

``` bash
$ inspect eval challenges.py --model google/gemini-1.5-pro
```

You can also evaluate multiple models at once:

``` bash
$ inspect eval challenges.py --model openai/gpt-4o,google/gemini-1.5-pro
```

To evaluate individual challenges specify them with \@:

``` bash
$ inspect eval challenges.py@db_3 --model google/gemini-1.5-pro
$ inspect eval challenges.py@idor --model openai/gpt-4o 
```

### Agent

The challenges are by default evaluated using a basic ReAct agent that implements a tool use loop with encouragement for the model to keep going if its gives up. The default agent can be customised using the following task options:

| Option | Description |
|------------------------------------|------------------------------------|
| `max_attempts` | The number of incorrect submissions to allow before ending the challenges (defaults to 1). |
| `max_messages` | The maximum number of messages allowed in the conversation before ending the challenges (defaults to 50). |

For example:

``` bash
$ inspect eval challenges.py --model openai/gpt-4o \
    -T max_attempts=2 -T max_messages=75
```

You can also run the task with an entirely different solver agent suing the `--solver` option. For example, if you have defined a solver agent in the source file `myagent.py`:

```bash
$ inspect eval challenges.py --solver myagent.py --model google/gemini-1.5-pro
```

### Epochs

The GDM paper evaluated each challenge 10 times, reporting success if at least 1 challenge of the 10 was successful. The same default number of epochs (10) is used here, however you can modify this with the `--epochs` option:

``` bash
$ inspect eval challenges.py --epochs=5 --model openai/gpt-4o 
```


## Docker Images

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