# Hackathon project

Generic lifecycle hooks for Inspect AI, to support integration with tools like Weights &
Biases.

W&B is a popular AI development platform that helps teams track experiments, visualize
data, and collaborate on AI projects.

Initially there are hooks for events like eval start, sample scored, token usage, etc.

Hooks can be used for other purposes like collecting audit logs or creating token usage
dashboards.

This lays the groundwork for collecting data like OpenAI web search tool usage
(requested within AISI) and will allow other orgs to implement tools like aisitools.

## Features

* Generic Inspect lifecycle hook system (e.g. eval start, sample scored, model usage,
  etc.)
* Hooks have typed function signatures
* Multiple hooks can register for same events (e.g. for model usage events, both
  aisitools could log it to AWS and W&B could log it too)
* A subscriber need only implement handlers for the events it cares about
* Changes to schema can be backward compatible (we're passing a single dataclass, rather
  than a bunch of positional arguments)

```py

@lifecycle_hook(name="w&b_hook")
class WBHook(LifecycleHook):
    async def on_eval_start(self, event: EvalStartEvent) -> None:
        wandb.init(name=event.run_id)

    async def on_sample_scored(self, event: SampleScoredEvent) -> None:
        wandb.log({
            "sample_id": event.sample_id,
            "score": event.score
        })

    async def on_eval_end(self, event: EvalEndEvent) -> None:
        wandb.finish()

```

Can imagine other hooks like collecting audit data, logging model usage, etc. (like we
do in aisitools).

## Demo

```sh
inspect eval examples/aisi_wandb_hook.py@theory_of_mind --model openai/gpt-4o
```

In W&B, show:
* diff.patch
* system stats
* dataframe
* All runs (statuses etc.)

## What's next?

* Make the the hooks system production-ready, PR into inspect.
* Update aisitools to use this new hooks system.
* Add web search hook and record this to AWS as part of aisitools.
* Investigate whether W&B Weave would be better suited than W&B Models.
