# GDM Dangerous Capabilities: In House CTF

This directory includes 13 Capture The Flag challenges migrated from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)). 

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation. 

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. The Dockerfiles used to build these images have been provided as well, they are adapted from the original repository with minor modifications. 

Note that the flag values in the Dockerfiles have been replaced with placeholders `REPLACE_ME_WITH_RANDOM_FLAG_N` to prevent them from ending up in scrapable GitHub data, the actual values are baked into the remote Docekr images and will be accessed during evaluation run. If you'd like to build your local images, make sure to replace these placeholders with your actual flag values and update the `compose.yaml` files accordingly.

## Evaluation

To evaluate all of the challenges against various models (a separate Inspect task and log file will be created for each challenge):

```bash
$ inspect eval task.py --model openai/gpt-4o
$ inspect eval task.py --model anthropic/claude-3-opus-20240229
$ inspect eval task.py --model google/gemini-1.5-pro
$ inspect eval task.py --model mistral/mistral-large-latest
```

To evaluate individual challenges:

```bash
$ inspect eval task.py@idor --model google/gemini-1.5-pro
$ inspect eval task.py@db_3 --model google/gemini-1.5-pro
```

### Options

There are two other optional task parameters:

- `max_attempts` defines the number of incorrect submissions to allow before ending the challenges (defaults to 1).
- `max_messages` defines the maximum number of messages allowed in the conversation before ending the challenges (defaults to 50).

For example:

```bash
$ inspect eval task.py --model openai/gpt-4o -T max_attempts=2 -T max_messages=75
```

