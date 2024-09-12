# In House CTF Tasks
This directory includes Capture The Flag challenges migrated from Google DeepMind's [Dangerous Capabilities Evaluations](https://github.com/google-deepmind/dangerous-capability-evaluations/tree/main/in_house_ctf) (originally published in [Evaluating Frontier Models for Dangerous Capabilities](https://arxiv.org/pdf/2403.13793)). 

This implementation uses [tool calling](https://inspect.ai-safety-institute.org.uk/tools.html) to enable the model to execute bash commands. The flag values has been replaced with placeholders `REPLACE_ME_WITH_RANDOM_FLAG_N` to prevent them from ending up in scrapable GitHub data, the actual values will be updated during evaluation run.

Note that the bash commands are executed inside Docker containers, so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation. Each task runs an attacker container and one or more challenge enviroment containers using the task-specific `compose.yaml` files, and the Dockerfiles for these tasks
are adapted from the original repository with minor modifications. 

To evaluate against various models:

```bash
$ inspect eval task.py --model openai/gpt-4-turbo
$ inspect eval task.py --model anthropic/claude-3-opus-20240229
$ inspect eval task.py --model google/gemini-1.5-pro
$ inspect eval task.py --model mistral/mistral-large-latest
```

If you are experiementing, you might find it useful to evaluate only a random subset of the samples by using the `excluded` task parameter. 

```bash
$ inspect eval task.py --model openai/gpt-4o -T excluded='["privesc_bash","privesc_find","privesc_sed"]'
```