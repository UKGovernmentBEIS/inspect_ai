# In House CTF Tasks
This directory includes Capture The Flag challenges migrated from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)). 

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation. 

Each task runs using the task-specific `compose.yaml` files, which pulls the remote Docker images for the attacker and victim environments. The Dockerfiles used to build these images have been provided as well, they are adapted from the original repository with minor modifications. Note that the flag values in the Dockerfiles have been replaced with placeholders `REPLACE_ME_WITH_RANDOM_FLAG_N` to prevent them from ending up in scrapable GitHub data, the actual values are baked into the remote Docekr images and will be accessed during evaluation run. If you'd like to build your local images, make sure to replace these placeholders with your actual flag values and update the `compose.yaml` files accordingly.

To evaluate against various models:

```bash
$ inspect eval task.py --model openai/gpt-4o
$ inspect eval task.py --model anthropic/claude-3-opus-20240229
$ inspect eval task.py --model google/gemini-1.5-pro
$ inspect eval task.py --model mistral/mistral-large-latest
```

By default, `max_messages` is set to 30, and `max_attempts` is set to 1, you can update them to your needs.
```bash
$ inspect eval task.py --model openai/gpt-4o -T max_messages=40 -T max_attemps=3
```

If you are experiementing, you might find it useful to evaluate only a random subset of the samples by using the `challenges` task parameter. 

```bash
$ inspect eval task.py --model openai/gpt-4o -T challenges='["cmd_injection", "privesc_7z"]'
```