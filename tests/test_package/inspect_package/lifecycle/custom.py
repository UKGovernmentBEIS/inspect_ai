from inspect_ai._util.lifecycle import EvalStartEvent, LifecycleHook


class CustomLifecycleHook(LifecycleHook):
    async def on_eval_start(self, event: EvalStartEvent) -> None:
        global run_ids
        run_ids.append(event.run_id)


run_ids: list[str] = []
